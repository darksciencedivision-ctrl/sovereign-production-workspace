# REPORT_desktop2 (incremental)
Area: apps/desktop/ (remaining scope) — reviewer: desktop2. HEAD bad029e7. Started 2026-08-16.
Continues REPORT_desktop.md (do not redo: R-39, R-71, R-72, R-46, R-17, R-44, R-45, R-70, R-73, R-14b, launch-source containment, conductor:succeed, approvals:decide, recovery restore, renderer innerHTML, quit-path scan).

## Working notes
(appended as I go)

### Notes batch 1 — logger + credentials
- main-process-logger.js in the LIVE tree is **107 lines**, not 200+. Prior reviewer's cites (":134,148", ":200", ":204-209") are off-by-file/version; the SEMANTIC claims still hold at the real lines:
  - `fs.mkdirSync(path.dirname(file),{recursive:true})` at :26 (module-construction time, i.e. main.js:312 top level)
  - `fs.appendFileSync(file, line+"\n")` per line at :39-41 — **no try/catch**
  - `rendererSink(line)` for EVERY line at :92 → main.js:315-317 `win.webContents.send("shell:log", line)`
  - `flushAndDetach()` :96-101 awaits `settledWaiters` with **no timeout**
  - **no rotation, no size cap, no TTL anywhere in the file** → R-56 CONFIRM (corrected line cites).
- Credentials: gateway prints `IPC_TOKEN=`/`IPC_KEY=` on **stdout** (control_plane/ipc/run_gateway.py:75-76); main.js:445-455 parses stdout and NEVER logs it; only `proc.stderr` is logged verbatim (main.js:456 `[gateway] ...`). `ipc/client.js` (151 lines) contains **zero** log/console statements; token/key live in `_token`/`_key` (:53-54) and go into the envelope only (:96). No token is ever sent to the renderer or written to disk by desktop code. [OBSERVED]
- `IPC_PORT/IPC_TOKEN/IPC_KEY` env override at main.js:427-430 accepts a pre-supplied credential with no validation (port not range-checked; `Number()` of junk → NaN → connect fails). INFO only.

### Notes batch 2 — mutation harnesses (scope item 4)
- **All five JS harnesses mutate PRODUCT FILES IN PLACE in this repo.** No `mkdtemp`/`tmpdir` anywhere in `tools/mutation/*.js` (grep: 0 hits). They `fs.writeFileSync` the real `apps/desktop/main.js`, `control/pane-writer.js`, `control/worker-readiness.js`, `voice/turn-authority.js`, `mcp_server/collaboration_service.py`, `control_plane/policy.py`, … and restore from memory. Under the read-only rule **none is runnable**; I did NOT run them. (Also true of `_op*_*.py`.)
- Substitute verification I CAN do read-only: **the pinned baselines are all current on HEAD bad029e7.** sha256(UPPER) of every pinned file equals its pin:
  - application-control.js / operational-state.js / sovereign-control-server.js / collaboration_service.py / policy.py / worker-spawn.js / operational-source.js / assignment-gate.js (orchestration_mutations.js:41-84) — 8/8 MATCH
  - main.js `D74E32DF…93D0` (pane_input:168, system_pane_write:185) MATCH; worker-readiness.js `494E01FB…8037` (readiness:74, system_pane_write:195) MATCH; pane-writer.js `118062B3…29F2` MATCH; conductor-readiness.js `B264243D…1D49` MATCH.
  ⇒ the "silent exit 3 / stale pin" failure the orchestration harness header confesses to (lines 12-17) is NOT currently present. [OBSERVED]
- **NEW D2-1 (LOW): `disarm_authority_mutations.js` has no pinned baseline** — it adopts on-disk bytes as ORIGINAL (:119) and then verifies restoration against that same copy (:150-155), which is exactly the circularity `pane_input_bypass_mutations.js:26-34` documents and defends against with `PINNED_BASELINE`. A run started on an already-mutated `voice/turn-authority.js` prints `BYTE-IDENTICAL` over the bypass. Fix: add the same pin table.
- **NEW D2-2 (LOW): lock-file split.** `disarm_authority_mutations.js:24` takes `.disarm-authority.lock` while pane_input / system_pane_write / readiness share `.mutation.lock` (their headers say they share it *because* both mutate main.js). Disarm's file set does not overlap, but its graded suites run `node --test` inside `apps/desktop` while another harness may have `main.js` mutated → cross-harness false GREEN/RED. Fix: one lock for the whole `tools/mutation` family.
- **EXECUTED (read-only substitute for running the harnesses): static anchor-uniqueness check.** I extracted each harness's mutation table in a `vm` sandbox with `fs.writeFileSync` blocked and `spawnSync` stubbed (script: scratchpad/desktop2/anchor_check.js), then counted each `find` anchor in the real product file. Result: **5 harnesses, 119 mutations, 127 anchor edits, 0 non-unique / 0 missing.** Combined with the 12/12 pin match above, every harness would run all of its mutations on HEAD today (no silent SKIP, no exit-3). `git status --porcelain` unchanged after the run. [OBSERVED]

### Notes batch 3 — gateway child pid (scope item 6) [OBSERVED, twice]
Setup mirrors main.js:437 (`spawn("py",["-3.12","-m",...])`) and main.js:2520 (`gatewayProc.kill()`).
- `py -3.12 -c "import time;time.sleep(60)"` → py.exe pid P, **separate** python.exe child C (ParentProcessId=P). Confirms the premise: `gatewayProc.pid` is the LAUNCHER, not the interpreter.
- `proc.kill()` (SIGTERM → libuv TerminateProcess on P): **3 s later BOTH P and C are gone** (run 1: `Get-CimInstance` returned zero py/python rows; run 2: `alive=False` for both explicit pids).
⇒ **REFUTE the "real Python gateway survives an Electron quit" hypothesis on this host.** The 3.12 `py.exe` launcher puts the interpreter in a job object that is killed on launcher exit, so the tree is reaped. Residual, narrower points [INFERRED]:
  (a) `waitForChildExit` (main.js:2523-2538) resolves on the LAUNCHER's `exit` event, which fires immediately on TerminateProcess; the interpreter's job-object reap is asynchronous and unobserved — so "gateway exited" in the teardown log is a claim about py.exe only.
  (b) the gateway is always killed HARD (no SIGINT/graceful close first), so `control_plane.ipc.run_gateway` never gets to close sockets/flush state on a normal quit.
