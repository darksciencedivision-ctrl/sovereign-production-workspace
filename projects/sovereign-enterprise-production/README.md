# SOVEREIGN - Enterprise Production Package (3.1.2)

Private release archive for the **SOVEREIGN 3.1.2** enterprise production line - the deterministic local
multi-model research pipeline (debate orchestration, claim arbitration, synthesis, publication gate) that
the Sovereign Workspace Shell (SWS-UI-001) fronts as module `sovereign` on port 5175.

Everything here is stored byte-for-byte as supplied in `D:\Product Software\` (`.gitattributes` disables
all text conversion). The live production tree is `D:\Sov 1\` (operator-owned, not a git repository);
the public [`sovereign`](https://github.com/darksciencedivision-ctrl/sovereign) repository holds the earlier v1.0 research
release (March 2026), not this line.

## Contents

| File | Size | What it is | SHA-256 |
|---|---|---|---|
| `SOVEREIGN_ENTERPRISE_PRODUCTION_20260813_142520.zip` | 453,948 B | Enterprise production package (126 entries under `SOVEREIGN/`): runtime, `sovereign_product/`, `synthesis/`, `arbitration/`, `broker_v21/`, `ui/ui_shell/dist/`, Start/Stop/Test/Diagnose PowerShell scripts, `PACKAGE_MANIFEST.txt`, `SYSTEM_MANIFEST.json`, `README_PRODUCTION.md` | `150e518e6d0b15b524ff61cda8fe8eb29aec6bbfb30196f9931908d12ff7ec51` |
| `SOVEREIGN_ENTERPRISE_PRODUCTION_20260813_142520_REPORT.pdf` | 70,371 B | Production package report (PDF) | `082619f339e093fdf5e87a8f893bc7c9970540fabf1cd2902b53df795d7c071e` |
| `SOVEREIGN_RAW_SOURCE_20260813_144541.zip` | 388,548 B | Raw source export (107 entries under `SOVEREIGN_SOURCE/`) | `1f14d2fab14547c7529e5e9420b87c0c2b814fc9ea464b5006e5db452571f770` |
| `SOVEREIGN_RAW_SOURCE_20260813_144541.pdf` | 1.9 MB | Plaintext rendering of the raw source export (PDF) | `f67fddf73c06f498e09957873ed68fa67619a064863be6a72adbd90c79e27499` |

## Notes

- The package ships `PACKAGE_MANIFEST.txt` and `SYSTEM_MANIFEST.json`; the workspace installs it into
  `modules/sovereign`, creates a workspace-owned venv and pins the resolved dependency set in
  `WORKSPACE-RESOLVED-LOCK.txt` (see `workspace/modules/sovereign/INSTALL-PROVENANCE.json`).
- The package includes the built UI bundle (`ui/ui_shell/dist/`), so no Node toolchain is needed to run it.

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
- [`sovereign-enterprise-production`](https://github.com/darksciencedivision-ctrl/sovereign-enterprise-production) - SOVEREIGN 3.1.2 enterprise production package <- this repository
- [`debate-table-production`](https://github.com/darksciencedivision-ctrl/debate-table-production) - Debate Table v1.2 Phase 1 production package
- [`sow-multi-model-terminal`](https://github.com/darksciencedivision-ctrl/sow-multi-model-terminal) - Sovereign Orchestration Workspace / Multi-Model Terminal baseline + independent review
- [`sovereign-distillery-enterprise`](https://github.com/darksciencedivision-ctrl/sovereign-distillery-enterprise) - Sovereign Distillery enterprise snapshot + raw source export
- [`product-software-artifacts`](https://github.com/darksciencedivision-ctrl/product-software-artifacts) - earlier flat archive of the same top-level files (2026-08-20); superseded by the organized repositories above
