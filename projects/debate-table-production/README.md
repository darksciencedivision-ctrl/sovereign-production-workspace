# Debate Table - v1.2 Phase 1 Production Package

Private release archive for **Debate Table v1.2 Phase 1**, the FastAPI debate web application that the
Sovereign Workspace Shell (SWS-UI-001) fronts as module `debate` on port 8700.

Everything here is stored byte-for-byte as supplied in `D:\Product Software\` (file names included;
`.gitattributes` disables all text conversion). This is the shipped package, not the development
history - the source tree lives in the `D:\Debate table` working repository (local only, no remote).

## Contents

| File | Size | What it is | SHA-256 |
|---|---|---|---|
| `Debate_Table_v1.2_Phase1_Production_20260811_201116 - Copy.zip` | 232,589 B | Production package: `Debate_Table_v1.2_Phase1_Production/` (35 entries: `app.py`, `debate/`, `scripts/`, `snapshot/`, `static/`, `tests/`, `MANIFEST-SHA256.json`, `requirements.lock.txt`, README / PRODUCTION-README / SNAPSHOT-RESTORE) **plus** an appended `SOW_REVIEW_ROUND2_RAW/` folder (9 files) - see integrity note | `29b364b075e55b4ac5e66cd1399145838dfca691d82c4500253d4ece36742f93` |
| `Debate_Table_v1.2_Phase1_Production_20260811_201116.zip - Copy.sha256` | 122 B | Original packaging checksum for the production zip as built 2026-08-11 (`be6cfe8c...`) | `744719f23f948d2b15a011e0d210eb2622470f98478075eefb2f6cbe243dc2b4` |
| `Debate_Table_v1.2_Phase1_Enterprise_Package_Report - Copy.pdf` | 6,031 B | Enterprise package report (PDF) | `2dbcad0c67db6380a569e1cc29fcc07c58968befc4522bd716f911fa34cb8493` |
| `Debate_Table_Raw_Plaintext_Source_20260812_154511 - Copy.zip` | 170,115 B | Raw plaintext source export of 2026-08-12 (`Debate_Table_Raw_Plaintext_Source/`, 19 entries) **plus** the same appended `SOW_REVIEW_ROUND2_RAW/` folder | `c308bec7fcb54d41ff2861d7c8742257d8d55aac0adc64223bac4c62327cbd1a` |

## Integrity notes

- The package ships its own `MANIFEST-SHA256.json` (34 content files). After extraction, verify with the
  one-liner in the workspace README (`workspace/README.md` -> *Install*, step 2).
- `... .zip - Copy.sha256` records `be6cfe8c...` for the production zip **as originally packaged on 2026-08-11**.
  The copy present here (`... - Copy.zip`, last modified 2026-08-19) hashes to `29b364b0...` because a
  `SOW_REVIEW_ROUND2_RAW/` folder (the nine SOW round-2 reviewer reports) was appended to it - and to the
  raw-source zip - after packaging. The packaged `Debate_Table_v1.2_Phase1_Production/` tree itself is
  unchanged: the workspace installer removed that folder from the runtime instance and re-verified all
  34 packaged files against `MANIFEST-SHA256.json` with 0 mismatches (workspace `evidence/phase2-debate-verify.txt`,
  `modules/debate/INSTALL-PROVENANCE.json`). Nothing was altered for this repository; the discrepancy is
  recorded here rather than "fixed". The canonical copy of those nine reports is
  [`sow-multi-model-terminal`](https://github.com/darksciencedivision-ctrl/sow-multi-model-terminal) `review/SOW_REVIEW_ROUND2_RAW/`.

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
- [`debate-table-production`](https://github.com/darksciencedivision-ctrl/debate-table-production) - Debate Table v1.2 Phase 1 production package <- this repository
- [`sow-multi-model-terminal`](https://github.com/darksciencedivision-ctrl/sow-multi-model-terminal) - Sovereign Orchestration Workspace / Multi-Model Terminal baseline + independent review
- [`sovereign-distillery-enterprise`](https://github.com/darksciencedivision-ctrl/sovereign-distillery-enterprise) - Sovereign Distillery enterprise snapshot + raw source export
- [`product-software-artifacts`](https://github.com/darksciencedivision-ctrl/product-software-artifacts) - earlier flat archive of the same top-level files (2026-08-20); superseded by the organized repositories above
