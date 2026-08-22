# Publishing record

## How this repository was produced

1. `D:\Product Software\` was read-only throughout. The SWS-UI-001 envelope (`workspace/AGENTS.md` section 9) forbids
   the builder from running git inside the workspace tree, and `workspace/evidence/manifests/*` hash that tree, so
   the repository was staged from a **copy** (operator instruction, 2026-08-22) and the source tree was never modified.
2. `workspace/` selection rules are implemented in `tools/publish/sync_workspace.py` (docstring); the same rules produced
   the first publication. Everything left out is enumerated in `EXCLUDED-FROM-REPO.txt`.
3. `projects/` holds the four deliverable repositories verbatim (their own `README.md` + `SHA256SUMS.txt` included).

## Byte exactness

- Root `.gitattributes` is `* -text`; commits are made with `core.autocrlf=false`.
- **Caveat found at verification:** `workspace/modules/sow/.gitattributes` (part of the SOW tracked tree) says
  `* text=auto eol=lf`, and a nested `.gitattributes` outranks the root one. Under that rule git LF-normalised
  `workspace/modules/sow/docs/loop/LOOP_STATE.json` (CRLF on disk) at the first commit. `.git/info/attributes`
  (`* -text`, highest precedence; written by the sync tool) plus `git add -A && git add --renormalize -A` corrected it. Anyone
  re-committing into this repository must keep `.git/info/attributes = * -text` or the nested rule re-applies.
- Clone on Windows with `git -c core.autocrlf=false -c core.longpaths=true clone ...` (the Distillery bundle has
  paths longer than 260 characters under deep checkout roots).

## Verification performed

Fresh clones of all five repositories were checked: every file matched `SHA256SUMS.txt`, and every file that has a
counterpart in `D:\Product Software\` was byte-identical to it (the only non-matching files were those the live
Gate 5b session rewrote after the snapshot; see `SNAPSHOT.json` for the snapshot time).

## Refreshing the workspace snapshot

From a clone of this repository on the host that holds `D:\Product Software\`:

```powershell
py -3.12 tools\publish\sync_workspace.py          # add --dry-run to preview
git add -A && git add --renormalize -A
git commit -m "Re-sync workspace snapshot <UTC from SNAPSHOT.json>"
git push origin main
```

The tool never writes to the source tree. Run it only when no SWS-UI-001 gate session is writing evidence.
