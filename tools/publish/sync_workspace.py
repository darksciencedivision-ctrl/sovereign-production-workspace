#!/usr/bin/env python3
"""Re-synchronise  workspace/  in this repository from  D:\\Product Software\\Production Workspace\\.

Selection rules (identical to the ones used for the first publication):
  * everything outside modules/          except __pycache__/ and *.pyc
  * modules/debate     files present in the Debate Table production zip  + INSTALL-PROVENANCE.json
  * modules/sovereign  files present in the SOVEREIGN production zip     + INSTALL-PROVENANCE.json, WORKSPACE-RESOLVED-LOCK.txt
  * modules/sow        files tracked by the live SOW git repository (read live if possible, else
                       tools/publish/sow_tracked.txt) + INSTALL-PROVENANCE.json + docs/evidence/**,
                       never: node_modules, __pycache__, .pytest_cache, .sovereign_store, %SystemDrive%,
                       .approvals, .recovery, .voice-captures, docs/loop/logs, *.pyc *.log *.db *.sqlite
Then it removes files under workspace/ that are no longer selected, rewrites EXCLUDED-FROM-REPO.txt,
SHA256SUMS.txt (every file except the root manifest itself) and SNAPSHOT.json, and makes sure
.git/info/attributes forces  * -text  so nested .gitattributes inside modules/ cannot normalise bytes.

It never writes to the source tree. Afterwards run, from the repository root:
    git add -A && git add --renormalize -A
    git commit -m "Re-sync workspace snapshot <UTC>"
    git push origin main
"""
import argparse, datetime, hashlib, json, os, shutil, subprocess, sys, zipfile
from collections import Counter
from pathlib import Path

JUNK_DIRS = {"node_modules", "__pycache__", ".pytest_cache", ".sovereign_store", "%SystemDrive%",
             ".approvals", ".recovery", ".voice-captures"}
JUNK_SUFFIX = {".pyc", ".log", ".db", ".sqlite", ".sqlite-wal", ".sqlite-shm"}
SOW_LIVE = Path(r"D:\multi model terminal app\sovereign-orchestration-workspace")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def zip_members(zpath: Path, strip: str) -> set:
    out = set()
    for n in zipfile.ZipFile(zpath).namelist():
        if not n.endswith("/") and n.startswith(strip):
            out.add(n[len(strip):])
    return out


def sow_tracked(repo: Path) -> set:
    saved = repo / "tools" / "publish" / "sow_tracked.txt"
    if SOW_LIVE.is_dir():
        try:
            env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
            out = subprocess.run(["git", "-C", str(SOW_LIVE), "ls-files"], capture_output=True, text=True,
                                 check=True, env=env).stdout
            files = {l for l in out.splitlines() if l}
            if files:
                saved.write_text("\n".join(sorted(files)) + "\n", encoding="utf-8", newline="\n")
                return files
        except Exception as e:  # fall back to the saved list
            print(f"note: could not read live SOW tracked list ({e}); using {saved.name}", file=sys.stderr)
    return {l for l in saved.read_text(encoding="utf-8").splitlines() if l}


def select(src: Path, repo: Path):
    """Yield (category, rel_posix, abs_source) for every file under src; category None = include."""
    dt_zip = next((repo / "projects" / "debate-table-production").glob("Debate_Table_v1.2_Phase1_Production_*.zip"))
    sv_zip = next((repo / "projects" / "sovereign-enterprise-production").glob("SOVEREIGN_ENTERPRISE_PRODUCTION_*.zip"))
    allow = {
        "debate": (zip_members(dt_zip, "Debate_Table_v1.2_Phase1_Production/"), {"INSTALL-PROVENANCE.json"}),
        "sovereign": (zip_members(sv_zip, "SOVEREIGN/"), {"INSTALL-PROVENANCE.json", "WORKSPACE-RESOLVED-LOCK.txt"}),
    }
    tracked = sow_tracked(repo)
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        parts = rel.parts
        relp = rel.as_posix()
        if parts[0] != "modules":
            if "__pycache__" in parts or p.suffix == ".pyc":
                yield "pycache", relp, p
            else:
                yield None, relp, p
            continue
        if len(parts) < 3:
            yield "modules stray", relp, p
            continue
        mod, inner = parts[1], Path(*parts[2:]).as_posix()
        if ".venv" in parts or "node_modules" in parts:
            yield f"modules/{mod} runtime", relp, p          # listed individually; aggregated below
            continue
        if mod in allow:
            members, extra = allow[mod]
            yield (None if (inner in members or inner in extra) else f"modules/{mod} runtime"), relp, p
        elif mod == "sow":
            if any(d in JUNK_DIRS for d in parts) or inner.startswith("docs/loop/logs/") or p.suffix in JUNK_SUFFIX:
                yield "modules/sow junk", relp, p
            elif inner in tracked or inner == "INSTALL-PROVENANCE.json" or inner.startswith("docs/evidence/"):
                yield None, relp, p
            else:
                yield "modules/sow untracked-local", relp, p
        else:
            yield "modules unknown", relp, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"D:\Product Software\Production Workspace")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    src, repo = Path(a.src), Path(a.repo)
    W = repo / "workspace"
    assert src.is_dir() and (repo / "projects").is_dir(), "bad --src/--repo"

    wanted, excluded = {}, []
    agg = Counter()
    for cat, relp, p in select(src, repo):
        if cat is None:
            wanted[relp] = p
        elif cat.endswith("runtime") and (".venv/" in relp or "node_modules/" in relp):
            agg[(cat, relp.split("/.venv/")[0] + "/.venv/" if ".venv/" in relp else relp.split("node_modules/")[0] + "node_modules/")] += 1
        else:
            excluded.append((cat, relp))
    for (cat, prefix), n in agg.items():
        excluded.append((cat, f"{prefix} (entire tree, {n} files)"))

    added = changed = removed = same = 0
    existing = {p.relative_to(W).as_posix(): p for p in W.rglob("*") if p.is_file()} if W.exists() else {}
    for relp, sp in sorted(wanted.items()):
        dp = W / relp
        if relp in existing:
            if dp.stat().st_size == sp.stat().st_size and sha(dp) == sha(sp):
                same += 1
                continue
            changed += 1
        else:
            added += 1
        if not a.dry_run:
            dp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sp, dp)
    for relp, dp in existing.items():
        if relp not in wanted:
            removed += 1
            if not a.dry_run:
                dp.unlink()
    if not a.dry_run:
        for d in sorted((d for d in W.rglob("*") if d.is_dir()), key=lambda d: -len(d.parts)):
            if not any(d.iterdir()):
                d.rmdir()

    utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cnt = Counter(c for c, _ in excluded)
    if not a.dry_run:
        (repo / "EXCLUDED-FROM-REPO.txt").write_text(
            "# Files present under " + str(src) + " that are deliberately NOT in this repository\n"
            "# (install-time / runtime state; regenerate via workspace/README.md -> Install).\n"
            "# <category>\\t<path relative to Production Workspace>\n"
            + "\n".join(f"{c}\t{r}" for c, r in sorted(excluded)) + "\n", encoding="utf-8", newline="\n")
        info = repo / ".git" / "info"
        if (repo / ".git").is_dir():
            info.mkdir(exist_ok=True)
            (info / "attributes").write_text("* -text\n", encoding="utf-8", newline="\n")
        root_sums = repo / "SHA256SUMS.txt"
        rows = [f"{sha(p)}  {p.relative_to(repo).as_posix()}" for p in sorted(repo.rglob("*"))
                if p.is_file() and p != root_sums and ".git" not in p.parts]
        snap = {"snapshot_utc": utc, "source": str(src), "workspace_files": len(wanted),
                "added": added, "changed": changed, "removed": removed, "unchanged": same,
                "excluded_by_category": dict(cnt)}
        (repo / "SNAPSHOT.json").write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8", newline="\n")
        rows = [r for r in rows if not r.endswith("  SNAPSHOT.json")] + [f"{sha(repo / 'SNAPSHOT.json')}  SNAPSHOT.json"]
        root_sums.write_text("\n".join(sorted(rows, key=lambda r: r.split('  ', 1)[1])) + "\n", encoding="utf-8", newline="\n")
    print(f"{utc}  workspace files={len(wanted)}  added={added} changed={changed} removed={removed} unchanged={same}")
    print("excluded:", dict(cnt))
    if not a.dry_run:
        print("next:  git add -A && git add --renormalize -A && git commit -m \"Re-sync workspace snapshot " + utc + "\" && git push origin main")


if __name__ == "__main__":
    main()
