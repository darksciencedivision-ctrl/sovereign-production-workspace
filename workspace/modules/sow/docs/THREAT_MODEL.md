# THREAT MODEL — Sovereign Orchestration Workspace
Adopted at Phase 0 (2026-07-16) from Architecture Plan v1.0.1 §3.3 (trust boundaries) and
§11 (threats T1–T16, failure modes), which incorporate Canonical Handoff §2.6. This file is
the build's working copy; the canonical text governs on any divergence.

## Trust boundaries

| TB | Boundary | Rule |
|---|---|---|
| TB-1 | Operator ↔ system | Only surface where authority enters; text and voice converge on one command bus **before** the Permission Broker |
| TB-2 | Control protocol ↔ terminal text | Only signed, schema-validated envelopes are control; model/harness terminal output is untrusted and never parsed as a command |
| TB-3 | Sovereign ↔ MCP | Requests carry authenticated node identity + role + task + scope; MCP holds **no** authorization logic; every write provenance-stamped, lands CANDIDATE unless role permits more |
| TB-4 | Node ↔ harness/model | Harness config (`AGENTS.md`, MCP config, model output) is node-controlled untrusted input; enforcement lives outside the harness (supervisor + broker + workspace isolation) |
| TB-5 | Voice ↔ command bus | Transcripts are proposals (`propose_command`), never executions; broker + approval queue in between |
| TB-6 | Profile boundary | Fail-closed loader; a cloud adapter requested under `offline_airgapped` aborts startup with a logged violation |

## Threats and mitigations

| # | Threat | Boundary | Mitigation |
|---|---|---|---|
| T1 | Terminal text parsed as control | TB-2 | Signed envelopes only (message@1.0); renderers never eval terminal output |
| T2 | Harness config injection (`AGENTS.md`, MCP config) | TB-4 | Node-controlled untrusted input; Sovereign policy never read from harness config; adversarial tests |
| T3 | Codex-class nested autonomy exceeding profile | TB-4 | Supervisor sandbox: worktree ACL, deny-by-default egress, broker-mediated exec; violations logged + node paused |
| T4 | Naked model/agent session joins orchestration | TB-4 | Registration refused unless supervisor-spawned (node@1.0); periodic process audit |
| T5 | Worker self-canonization / memory contamination | TB-3 | Server-side lifecycle enforcement (memory@1.0); CANDIDATE quarantined from ACCEPTED; gates only path to ACCEPTED |
| T6 | Silent last-write-wins on canonical memory | TB-3 | Immutable append + CAS + conflict_record objects |
| T7 | MCP server accumulates authority / compromised | TB-3 | No policy in MCP; Sovereign-signed authorization; separate process; read/append capability only |
| T8 | MCP outage mid-project | — | Fail-closed node behavior (F5); local checkpoints (checkpoint@1.0); reconciliation before resume |
| T9 | Voice mis-transcription → destructive action | TB-5 | Confidence threshold; propose-never-execute; clarification; approval queue; transcript log |
| T10 | Ambient/replayed audio issues commands | TB-5 | PTT/explicit trigger only; operator-presence assumption; protected actions always queued |
| T11 | Cloud adapter under offline profile | TB-6 | Fail-closed profile loader aborts startup |
| T12 | Voice audio exfiltration | TB-5/6 | Transcribe-then-discard; local-only TTL retention; zero egress offline (D-VOICE-04) |
| T13 | Subscription over-concurrency (ToS breach) | — | I-X3 governor in supervisor + status-bar visibility; raise only after R8 verification |
| T14 | CoWork silently modifies canonical files | TB-3 | Governed client class; canonical resources read-only to it; every access logged |
| T15 | Stale conductor state after succession | — | Staleness checklist before first assignment (F4 / Plan §19.1) |
| T16 | Debate as unbounded token sink | — | Cost governor: per-debate budget, per-caller quota, global cap, hard ≤5 rounds |

## Failure modes & recovery (Plan §11.2)

Control-plane crash → restart from SQLite WAL + last snapshots; nodes hold, reconcile,
resume. Node crash → TERMINATED in registry, task back to READY, worktree preserved for
forensics, respawn per policy. Conductor loss → succession (F4). GPU OOM (offline) →
residency planner evicts per policy, task queued with visible reason, never silent failure.
Disk-full → event-log write failure halts new writes fail-closed. WSL/Parakeet down →
voice surface disabled; text path unaffected (voice is never load-bearing).

## Build-time analogue (Buildout Directive §2.3)

The repo's own guardrails mirror T3/T4: `.claude/settings.json` deny rules +
`.claude/hooks/guard.py` hard-block writes outside the project root, edits to
`docs/canonical/`, and push/remote/network commands — enforcement by configuration,
not memory.
