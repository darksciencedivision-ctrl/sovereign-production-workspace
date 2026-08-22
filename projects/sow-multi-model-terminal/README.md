# Sovereign Orchestration Workspace (SOW) - Multi-Model Terminal

Private release archive for the **Sovereign Orchestration Workspace**: the Windows-native Electron + Python
multi-model terminal orchestration app (control plane, adapters for local/frontier/coding/voice providers,
MCP server, conductor, durable store). The Sovereign Workspace Shell (SWS-UI-001) fronts it as module `sow`
(Electron desktop app; launched only through the shell's self-check path).

Everything here is stored byte-for-byte as supplied in `D:\Product Software\` (`.gitattributes` disables
all text conversion). The live source repository is `D:\multi model terminal app\sovereign-orchestration-workspace`
(local only, no remote); the workspace repository vendors its tracked tree at commit `6d23a81` under
`workspace/modules/sow`.

## Contents

| File | Size | What it is | SHA-256 |
|---|---|---|---|
| `SOW_CONTINUATION_BASELINE_20260815_210626.candidate.zip` | 4.4 MB | Continuation baseline candidate (900 entries under `SOVEREIGN_ORCHESTRATION_WORKSPACE/`): full tracked tree - `apps/desktop` Electron app, `control_plane/`, `adapters/`, `mcp_server/`, `conductor/`, `tests/`, `tools/`, `docs/` registers and canon | `32f157b117ee70f17bafba9303a17a2adb5eab495fd554bd4e559a837aa2f3d7` |
| `SOW_CONTINUATION_BASELINE_PACKAGING_REPORT_20260815_210626.pdf` | 11,530 B | Packaging report for the baseline (PDF) | `ff2e9c8774cc1103d51c8679bb718dcf4d86d2db0ece386068eb64e4225ea151` |
| `SOW_RAW_PLAINTEXT_SOURCE_20260815_213158.zip` | 1.5 MB | Raw plaintext source export (311 entries under `SOVEREIGN_RAW_PLAINTEXT_SOURCE/`) | `5e303b70987d99728639dc8edfa2480cb7eca486d631b2e95abf1147e4bd90df` |
| `SOW_RAW_PLAINTEXT_SOURCE_20260815_213158.pdf` | 4.6 MB | Plaintext rendering of the raw source export (PDF) | `9b86b730b97364fd52b432365d981d01de843c9a6121b02100d96854fdcc1455` |
| `SOW_INDEPENDENT_REVIEW_WINDOWS_HOST_20260816.md` | 58,861 B | Independent adversarial review on the Windows host, 2026-08-16 (live tree at HEAD `bad029e7`): adjudicated findings A-1...A-9 plus threat-model / Electron triage | `72260296b736a114264a435b2ba518d9e1388a38d3017991c9a0d55cd6bfe392` |

### `review/SOW_REVIEW_ROUND2_RAW/`

Raw per-area reports from the round-2 independent review (inputs to `SOW_INDEPENDENT_REVIEW_WINDOWS_HOST_20260816.md`):

- `REPORT_adapters.md`
- `REPORT_control_plane.md`
- `REPORT_desktop.md`
- `REPORT_desktop2.md`
- `REPORT_evidence.md`
- `REPORT_mcp.md`
- `REPORT_security.md`
- `REPORT_security2.md`
- `REVIEWER_PREAMBLE.md`

`REVIEWER_PREAMBLE.md` is the shared read-only, no-provider-spend brief every scoped reviewer ran under.
(These nine files were also found appended inside the Debate Table "- Copy" zips; this directory is their
canonical home.)

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
- [`sow-multi-model-terminal`](https://github.com/darksciencedivision-ctrl/sow-multi-model-terminal) - Sovereign Orchestration Workspace / Multi-Model Terminal baseline + independent review <- this repository
- [`sovereign-distillery-enterprise`](https://github.com/darksciencedivision-ctrl/sovereign-distillery-enterprise) - Sovereign Distillery enterprise snapshot + raw source export
- [`product-software-artifacts`](https://github.com/darksciencedivision-ctrl/product-software-artifacts) - earlier flat archive of the same top-level files (2026-08-20); superseded by the organized repositories above
