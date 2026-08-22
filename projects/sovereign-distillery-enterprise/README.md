# Sovereign Distillery - Enterprise Snapshot `5ff6f56e`

Private release archive for the **Sovereign Distillery** - the model-forging subsystem of the Sovereign
research workspace (where SOVEREIGN, the Debate Table and the Multi-Model Terminal *use* models, the
Distillery *produces* them). The Sovereign Workspace Shell (SWS-UI-001) fronts it as module `distillery`
(file-driven status only; no process is launched).

Everything here is stored byte-for-byte as supplied in `D:\Product Software\` (`.gitattributes` disables
all text conversion). Both archives are also present **unpacked** (`SOVEREIGN_DISTILLERY_ENTERPRISE_20260821T011825Z_5ff6f56e/`, `SOVEREIGN_DISTILLERY_RAW_SOURCE_20260821T011825Z_5ff6f56e/`) so the source tree,
provenance and validation records can be browsed directly.

## Provenance (from `MANIFEST.json` / `PROVENANCE/`)

| | |
|---|---|
| Source repository | `D:\Sovereign-Grounded-Distillery` |
| Branch / commit | `remediation/hardware-rebaseline-pre-hg3` @ `5ff6f56ea4448cbdf7384cbcba0f64073934ca05` |
| origin/main at export | `44f69077f0d674bd7bef5730c2fe41a685e64b03` (`ryguy-pixel/Sovereign-Distillery`; local HEAD was 9 commits ahead, **no remote write performed** - this snapshot is the only published copy of those commits) |
| Created | 2026-08-21T01:18:25Z |
| Source files / bytes | 131 / 878,131 |
| Working tree clean | True |
| Validation | 43/43 PASS on Windows Python 3.14, Windows Python 3.11, and Ubuntu/WSL; schema PASS; security `NO_KNOWN_SECRET_OR_PRIVATE_RUNTIME_PAYLOAD_DETECTED`; weights present: False |
| Gate state | HG-0 `PASS` / HG-1 `ENFORCEMENT_PASS_D9_PENDING` / HG-2 `PASS_SYNTHETIC` / HG-3 `BLOCKED_HARDWARE_CAPACITY` / G2-G6 `NOT_STARTED` / D-9 `4_OF_4_UNKNOWN_FAIL_CLOSED` |
| Promotion / deployment | `NO_MODEL_PROMOTED` / `NO_PRODUCTION_DEPLOYMENT` |
| Pinned students (HG-3) | GND-STUDENT-4B `Qwen/Qwen3-4B-Base@906bfd4b` / GND-STUDENT-8B `Qwen/Qwen3-8B-Base@49e3418f` |

"Enterprise snapshot" describes packaging quality, not product maturity or certification
(`README_ENTERPRISE_SNAPSHOT.md`). Pattern-based secret scanning cannot guarantee discovery of every secret.

## Contents

| File | Size | What it is | SHA-256 |
|---|---|---|---|
| `SOVEREIGN_DISTILLERY_ENTERPRISE_20260821T011825Z_5ff6f56e.zip` | 809,904 B | Enterprise snapshot archive (155 entries): `SOURCE_TREE/` (all 131 tracked files), `HISTORY/` git bundle, `INVENTORY/`, `PROVENANCE/`, `VALIDATION/`, `MANIFEST.json`, `README_ENTERPRISE_SNAPSHOT.md` | `620e8459c74fb5fe9d2dfe0c4693cea02b8346292804d2d2a01fb71cb615be96` |
| `SOVEREIGN_DISTILLERY_ENTERPRISE_20260821T011825Z_5ff6f56e.zip.sha256` | 128 B | Checksum file for the enterprise archive (matches) | `f2c34a1aca91d568fed9ba190a6413a9d404509b8dcbaf22c23be83aa3344e8c` |
| `SOVEREIGN_DISTILLERY_RAW_SOURCE_20260821T011825Z_5ff6f56e.zip` | 65,147 B | Raw byte-preserving source export (42 entries; 37 `.py`/`.json` files under `SOURCE/` + ORIGIN / MANIFEST / SHA256SUMS / FILE_INVENTORY / EXCLUDED_SENSITIVE) | `7826dffbd59231058ad769155d7efc5e98fce11dea1bad6074630017a6e59cf9` |
| `SOVEREIGN_DISTILLERY_RAW_SOURCE_20260821T011825Z_5ff6f56e.zip.sha256` | 128 B | Checksum file for the raw-source archive (matches) | `13319ac9b60b5d3d544d11787f7e11ad333e6b605b1e08985b789bd390d59d5f` |
| `SOVEREIGN_DISTILLERY_EXPORT_REPORT_20260821T011825Z_5ff6f56e.json` | 6,418 B | Export report: validation, security scan, round-trip and classification results for both exports | `d5ed099e332e2f6977f8cf1233c96b797241b4ff1e4e999d19d03814a601dc00` |

- `SOVEREIGN_DISTILLERY_ENTERPRISE_20260821T011825Z_5ff6f56e/` - the enterprise archive, unpacked (155 files)
- `SOVEREIGN_DISTILLERY_RAW_SOURCE_20260821T011825Z_5ff6f56e/` - the raw-source archive, unpacked (42 files)

## Related repositories

- [`sovereign-distillery`](https://github.com/darksciencedivision-ctrl/sovereign-distillery) - thesis v1.1 with the D1-D4 / F.0-F.1 run records
- [`grounded-distillery`](https://github.com/darksciencedivision-ctrl/grounded-distillery) - private mirror of the Grounded Distillery thesis v1.1 (canonical: `ryguy-pixel/Sovereign-Distillery`)

## Verify

`SHA256SUMS.txt` lists a lowercase SHA-256 for every file in this repository. From PowerShell:

```powershell
Get-Content .\SHA256SUMS.txt | ForEach-Object {
  $hash, $name = $_ -split '  ', 2
  [pscustomobject]@{ File = $name; Valid = ((Get-FileHash -LiteralPath $name -Algorithm SHA256).Hash.ToLower() -eq $hash) }
}
```

Or from a POSIX shell: `sha256sum -c SHA256SUMS.txt`.

## Family

All repositories are private under `darksciencedivision-ctrl`:

- [`sovereign-production-workspace`](https://github.com/darksciencedivision-ctrl/sovereign-production-workspace) - the one project that completes the four: SWS-UI-001 Sovereign Workspace Shell + all four deliverable sets vendored under `projects/`
- [`sovereign-enterprise-production`](https://github.com/darksciencedivision-ctrl/sovereign-enterprise-production) - SOVEREIGN 3.1.2 enterprise production package
- [`debate-table-production`](https://github.com/darksciencedivision-ctrl/debate-table-production) - Debate Table v1.2 Phase 1 production package
- [`sow-multi-model-terminal`](https://github.com/darksciencedivision-ctrl/sow-multi-model-terminal) - Sovereign Orchestration Workspace / Multi-Model Terminal baseline + independent review
- [`sovereign-distillery-enterprise`](https://github.com/darksciencedivision-ctrl/sovereign-distillery-enterprise) - Sovereign Distillery enterprise snapshot + raw source export <- this repository
- [`product-software-artifacts`](https://github.com/darksciencedivision-ctrl/product-software-artifacts) - earlier flat archive of the same top-level files (2026-08-20); superseded by the organized repositories above
