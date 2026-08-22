# REPORT_security2 — SOW independent review (area: security2)
Repo: D:\multi model terminal app\sovereign-orchestration-workspace @ bad029e7 (read-only). Started 2026-08-16.
Continues REPORT_security.md (do not redo: STT confidence, verb matcher, turn-authority, control gateway, IPC_TOKEN, transcript/audio persistence, PII, .gitignore, listener inventory, path containment).

## Running log (appended incrementally)

---
## §3 Build harness: .claude/settings.json + .claude/hooks/guard.py — [OBSERVED, executed]
Probe: scratchpad/security2/probe_guard.py — imports the REAL guard module, calls `check_path()` and `main()` with a synthetic stdin payload, catches SystemExit. No repo file written. Host py 3.12.10 / Win11 26200. Real junctions created in %TEMP%, not in the repo.

### 3a. `docs/canonical/` freeze via check_path — HOLDS against every path trick
All of these DENY(2):
| Trick | raw | verdict |
|---|---|---|
| direct rel / abs | `docs/canonical/.gitkeep` | DENY (frozen) |
| dot-dot bounce | `docs/canonical/../canonical/NEW.md` | DENY (frozen) |
| deep bounce | `docs/../docs/canonical/NEW.md` | DENY (frozen) |
| mixed case | `DOCS/CANONICAL/NEW.md` | DENY (frozen) |
| ALL-CAPS absolute | `D:\MULTI MODEL...\DOCS\CANONICAL\NEW.md` | DENY (frozen) |
| 8.3 short name | `GetShortPathNameW` returns the LONG name on this volume (8.3 generation appears disabled) — no short name exists to abuse | n/a |
| junction %TEMP%\junc→docs/canonical | `...\junc_to_canonical\NEW.md` | DENY (frozen) — `resolve()` follows the junction |
| junction %TEMP%\junc→repo root | `...\junc_to_repo\docs\canonical\NEW.md` | DENY (frozen) |
| `\?\` prefix | `\?\D:\...\docs\canonical\NEW.md` | DENY — but as **"write outside project root"**, not "frozen": pathlib keeps the `\?\` prefix so it is not recognised as inside the root either. Denies for the wrong reason; still denies. |
| `\.\` prefix | `\.\D:\...\docs\canonical\NEW.md` | DENY (frozen) |
| ADS | `docs/canonical/.gitkeep:evil`, `::$DATA` | DENY (frozen) |
| trailing dot / space | `docs/canonical/NEW.md.` / `NEW.md ` | DENY (frozen) |
| forward slashes | `D:/.../docs/canonical/NEW.md` | DENY (frozen) |
| UNC admin share | `\localhost\D$\...\docs\canonical\NEW.md` | DENY (outside root) |
| `\?\UNC\localhost\D$\...` | DENY (outside root) |
| GLOBALROOT device path | DENY (unresolvable) |
Root containment: `C:\Windows\Temp\x.txt` DENY, `../outside.txt` DENY.
Verdict: **check_path itself is genuinely solid.** Windows path-comparison being case-insensitive (`PurePath.__eq__` normcase) plus `resolve()` following junctions covers the whole class. This is the strongest single control in the build harness.

Residual in check_path (LOW/INFO):
- `docs/canonical/N\x00EW.md` → uncaught `ValueError` from `stat` (guard.py:52 catches only `OSError`) → hook exits 1 → **non-2 exit = non-blocking in the Claude Code hook contract ⇒ fail-open**.
- `~/x.txt` ALLOW — no `expanduser()` in check_path (unlike the Bash branch at guard.py:80), so it joins to `REPO/~/x.txt`, inside root. Not an escape; noted because the two branches disagree about `~`.

### 3b. S-01 | HIGH | [OBSERVED] — The canonical freeze is not applied to the Bash tool at all
`main()` (guard.py:70-88) calls `check_path()` ONLY for `Write|Edit|MultiEdit|NotebookEdit` (:70-71). The `Bash` branch (:72-88) never calls `check_path` and has no `FROZEN` logic. Executed, all **ALLOW**:

    echo evil >  docs/canonical/Claude_Code_Buildout_Directive_20260716.md    ALLOW
    echo evil >> docs/canonical/NEW.md                                        ALLOW
    python -c "open('docs/canonical/NEW.md','w').write('x')"                  ALLOW
    sed -i 's/a/b/' docs/canonical/NEW.md                                     ALLOW
    cp /dev/null docs/canonical/NEW.md                                        ALLOW
    tee docs/canonical/NEW.md                                                 ALLOW

`Bash(python:*)`, `Bash(cat:*)`, `Bash(node:*)` are on the settings.json **allow** list (settings.json:44,57,43) — so these run without even a permission prompt. THREAT_MODEL.md:49-52 claims the harness "hard-block[s] … edits to `docs/canonical/`"; that claim is **true only for the four write tools**, and false for the tool class that is broadly pre-approved. Fix shape: in the Bash branch, run every redirect/`tee` target and every path-looking argument through `check_path`, or add a `Bash(*docs/canonical*)` deny.

### 3c. S-02 | MEDIUM | [OBSERVED] — The Bash "redirect outside project root" check is dead code on Windows
guard.py:77-88: the guard inspects a redirect target only if `target.startswith(("/","~",".."))` (:79) **and then** `p.is_absolute()` (:81). On Windows those two conditions are near-disjoint:
- `../outside.txt` → passes :79, `is_absolute()` False → **skipped**. Executed: `echo x > ../outside.txt` → **ALLOW**.
- `/c/Windows/Temp/x.txt` → passes :79, `PurePath('/c/...').is_absolute()` is False on Windows (no drive) → **skipped**. Executed → **ALLOW**.
- `D:\elsewhere\x.txt` → fails :79 (doesn't start with `/`, `~`, `..`) → never considered at all.
The only target class actually reaching the root check is `~/...` (expanduser makes it absolute). So on the target platform the redirect containment is effectively unreachable. `target.startswith("..") or target.startswith("../")` (:79) is also redundant. Fix shape: drop the `startswith` prefilter and the `is_absolute()` gate; resolve every target against `PROJECT_ROOT` and reuse `check_path`.

### 3d. S-03 | MEDIUM | [OBSERVED] — guard.py resolves relative paths against PROJECT_ROOT; the tool resolves against cwd
guard.py:49-50 (`if not p.is_absolute(): p = PROJECT_ROOT / p`). Executed with `cwd = REPO/docs`:

    raw='canonical/NEW.md'          -> ALLOW   (guard sees REPO/canonical/NEW.md, not frozen)
    raw='../docs/canonical/NEW.md'  -> DENY as "outside project root" (guard sees REPO/../docs/...)

Both verdicts are wrong relative to what a cwd-relative writer would actually touch (the first would land IN the frozen dir; the second would land inside the repo). Precondition: the write tool accepts a non-absolute `file_path` and resolves it against the session cwd — Claude Code's Write/Edit normally require absolute paths, so this is a latent divergence, not a live bypass today. But it is a false-ALLOW in the direction that matters. Fix shape: resolve relative inputs against the hook payload's `cwd` field, or deny non-absolute paths outright.

### 3e. S-04 | MEDIUM | [OBSERVED] — guard.py fails OPEN on every error path
Four fail-open routes, three executed:
- malformed stdin → explicit `sys.exit(0)`, comment "defer to permission rules" (guard.py:66-67). Exit 0 = allow.
- `tool_input.command` a non-string (e.g. a JSON list) → `TypeError` at guard.py:75 → uncaught traceback → exit 1. The Claude Code hook contract blocks only on **exit 2**; a non-2 non-zero exit is a non-blocking error, so the Bash command proceeds. Executed: `{"tool_name":"Bash","tool_input":{"command":["curl","x"]}}` → TypeError traceback.
- NUL byte in `file_path` → `ValueError` from `stat` escapes the `except OSError` at guard.py:52-54 → exit 1 → non-blocking.
- The hook command is bare `python "$CLAUDE_PROJECT_DIR/.claude/hooks/guard.py"` (settings.json:71,80). If `python` is absent from PATH, is the Microsoft Store stub, or is a version that cannot parse the file, the hook exits non-2 and **every** Write/Edit/Bash is unguarded, silently and with no operator signal.
CLAUDE.md's own rule is "Fail closed on ambiguity"; this file does the opposite in four places. Fix shape: wrap `main()` in `try/except BaseException: sys.exit(2)`; pin the interpreter to `py -3.12`.

### 3f. S-05 | MEDIUM | [OBSERVED] — BASH_BLOCK regexes are trivially evadable (and simultaneously over-block)
Executed against `main()`:

| command | verdict |
|---|---|
| `curl https://example.com` | DENY |
| `c"u"rl https://example.com` | **ALLOW** (shell quote-removal defeats `\bcurl\b`) |
| `cur\l https://example.com` | **ALLOW** |
| `g=push; git $g origin main` | **ALLOW** (variable indirection) |
| `git -c x=y push` | **ALLOW** (`\bgit\s+push\b` requires adjacency) |
| `rsync -a a b` | ALLOW — by design (guard.py:35 blocks only `rsync host::` / `rsync -e`), but rsync to a UNC target is still egress |
| `powershell -c "iwr https://x"`, `Invoke-WebRequest`, `Net.WebClient` | **ALLOW** — settings.json:21 denies `Bash(Invoke-WebRequest:*)` by command *prefix* only, and guard.py has no pattern for `iwr` / `Invoke-WebRequest` / `WebClient` / `Start-BitsTransfer` at all |
| false positives | `echo 'do not git push'` → DENY; `ssh-keygen -t rsa` → DENY (`\bssh\b`) |

Substring matching on a shell string is the wrong layer; the deterministic control the repo's own rules demand is an executable allow-list, not a regex deny-list.

### 3g. Network-denial porosity — concrete bypasses (confirms the lead's note)
settings.json denies curl/wget/ssh/scp/nc/Invoke-WebRequest/gh/git push, but **allows** (settings.json:39-48): `npm install:*`, `npm ci:*`, `npm run:*`, `npx:*`, `node:*`, `python:*`, `python3:*`, `py:*`, `pip install:*`, `pip3 install:*`. Each is a full egress **and** arbitrary-code channel:
1. `node -e "fetch('https://x')"` — allowed, guard silent (executed: ALLOW).
2. `python -c "urllib.request.urlopen(...)"` — allowed, guard silent (executed: ALLOW).
3. `npm install <pkg>` — network fetch **plus** arbitrary `postinstall` execution outside every guard (executed: ALLOW). Same for `npm ci`; `npx <pkg>` downloads-and-executes.
4. `pip install <pkg>` — network fetch + arbitrary `setup.py` execution (executed: ALLOW).
5. `npm run <script>` — runs whatever `package.json` says; `package.json` is not a frozen file and is writable by the same harness.
6. `powershell -c "iwr ..."` — no guard rule; stopped only if the operator declines the prompt.
7. `git fetch https://…` / `git clone https://…` — `\bgit\s+remote\b` and `Bash(git remote:*)` do not match either; `git checkout:*`, `git worktree:*`, `git merge:*` are all on the allow list.
So "deny-by-default egress" (THREAT_MODEL T3) is not what this configuration implements: it is a deny-list of four fetch binaries standing in front of an allow-list of two general-purpose interpreters and two package managers. Fix shape: drop blanket `python:*`/`node:*`/`npx:*`/`npm install:*` from `allow`, or enforce egress at the OS layer (which is what invariant 29 already says).

### 3h. Secondary — `Read(./.env)` deny is bypassable via allowed Bash | LOW | [OBSERVED]
settings.json:4-8 denies `Read(./.env)`, `Read(./.env.*)`, `Read(./secrets/**)`, `Read(**/credentials*)`, `Read(../**)`. But `Bash(cat:*)` (:57), `Bash(type:*)` (:58) and `Bash(python:*)` (:44) are allowed and guard.py has no read-path logic at all. `cat .env`, `cat secrets/x`, `cat ../../anything`, `py -c "print(open(r'C:\Users\Sslaw\.ssh\id_rsa').read())"` pass both layers. Also note `Read(./.env)` is root-anchored — `apps/desktop/.env` is not covered by any deny. Severity gated on whether such files exist locally (the lead found no tracked credentials).

### 3i. Secondary — allow-rule prefix semantics | INFO | [OBSERVED]
`Bash(powershell -ExecutionPolicy Bypass -File tools/loop:*)` (settings.json:61) is a *prefix* match: `tools/loop` also prefixes `tools/loopXYZ.ps1` and `tools/loop/../../anything.ps1`. `tools/loop/` contents are not frozen and are writable by the harness, so this rule pre-approves execution of any script the harness itself can author. Same class of issue as `Bash(python tools/manifest/compute_manifest.py:*)` (:32) — the trailing `:*` makes the whole argument vector free, e.g. `... compute_manifest.py; rm -rf x` if the runner passes the string to a shell.

---
## §2 Dangerous-call census, repo-wide (node_modules excluded) — [OBSERVED]

Patterns swept across `**/*.py`, `**/*.js|mjs|cjs`, `**/*.ps1|psm1` with ripgrep/grep:
`eval(`, `exec(`, `pickle`, `yaml.load`, `shell=True`, `os.system`, `child_process.exec/execSync`,
`new Function(`, `vm.runIn*`, `importlib`/`__import__`, `getattr/setattr` dispatch, `Invoke-Expression`,
`Add-Type`, `DownloadString`, `process.binding`, dynamic `require()`.

| Hit | product/test/tool | caller-controlled input reachable? | verdict |
|---|---|---|---|
| **Python `eval(` / `exec(` / `pickle` / `yaml.load` / `os.system` / `marshal`** | — | — | **ZERO occurrences anywhere in the tree.** Clean. |
| **`subprocess(..., shell=True)`** | — | — | **ZERO occurrences.** Every one of ~40 `subprocess.run/Popen` sites passes an argv **list**. `control_plane/nodes/process_manager.py:59` even carries `# noqa: S603 - argv is manager-controlled, no shell`. |
| `subprocess.list2cmdline(argv)` `node_runtime/supervisor/conductor_permission_profile.py:59` | product | argv is profile-derived | OK — used to *render* a line for logging, not to execute |
| `mcp_server/__init__.py:34-36` `importlib.import_module(module_name)` + `getattr` | product | **no** — `name` is checked against the fixed `_LAZY` dict (`:21-29`) *before* import; unknown names raise `AttributeError` (`:37`) | **safe by construction** (allow-list, not a name-to-module concatenation) |
| ~40 `getattr(obj, "literal", default)` sites (`adapters/**`, `node_runtime/supervisor/provider_node_registration.py:183-244`, …) | product | **no** — every attribute name is a string literal in source | not dispatch; duck-typing/defaulting only |
| `getattr(self, key) for key in CONDUCTOR_RECORD_KEYS` `control_plane/conductor/selection.py:112` | product | no — module-level constant tuple | safe |
| `getattr(R, name)` `tests/unit/test_frontier_provider_recon.py:400`; `getattr(signal, name, None)` `tools/mutation/_op18c_close_mutations.py:213` | test/tool | no | n/a |
| `__import__` in `tests/integration/test_wsl_parakeet.py:125`, `tests/unit/test_frontier_provider_recon.py:755-762`, `tools/mutation/_op18{c,d,e}_*.py` | test/tool | no — mutation harnesses that *write* mutated source strings to a temp copy to prove tests catch them | n/a |
| `child_process.spawn` — ~10 product sites (`apps/desktop/main.js:24`, `conductor/{source,spawn-source,dispatch-source,launch-source}.js`, `picker/source.js`, `statusbar/governor-source.js`, `approvals/drawer-source.js`, `inspector/operational-source.js`) | product | argv arrays only; the child is always `py -3.12 <repo-relative emitter>` | **`exec()`/`execSync()`/shell string form: ZERO in product.** Only `spawn`/`spawnSync`/`execFile` (array form) |
| `execFile` `apps/desktop/selfcheck/process-tree.js:3` | selfcheck tool | no | array form |
| `spawnSync("git", [...])` `apps/desktop/selfcheck/voice-conductor-selfcheck.js:186-196` | selfcheck | no | array form |
| `new Function(` / `vm.runIn*` / `process.binding` / dynamic `require(var)` | — | — | **ZERO occurrences** in product JS |
| `eval(` in JS | tool only — `tools/mutation/pane_input_bypass_mutations.js:223-224` (M8/M14 are *mutants* deliberately injected to prove the input-path guard catches an `eval`-by-name bypass) and `tools/spike_compositor/node_modules/**` (vendored) | no | n/a — this is the mutation harness testing FOR eval, not using it |
| `persistence/store.py:69 conn.executescript(...)` | product | **no** — a static DDL string literal; no interpolation | safe. No f-string/`+`-concatenated SQL found anywhere; all query sites use `?` params |
| **`Invoke-Expression (Invoke-RestMethod 'https://antigravity.google/cli/install.ps1')`** `tools/providers/run_frontier_providers.ps1:371` | tool (operator-run) | URL is a **hardcoded literal**; runs only under an explicit `-InstallMissing` switch (`:338-344`) | **the only remote-code-download-and-execute in the repo** — see S-06 |

### S-06 | LOW | [OBSERVED] — unpinned remote installer is the one RCE-shaped path, but it is disclosed and gated
`tools/providers/run_frontier_providers.ps1:355-378` fetches and `Invoke-Expression`s a vendor PowerShell
installer with **no checksum, no signature check, no TLS pinning**. Preconditions are real mitigations:
operator must pass `-InstallMissing` (`:337`), the provider must be `google_antigravity` and not already
installed (`:334-336`), and the code prints two explicit warnings that this is unverified remote code
(`:359-360`). It also correctly resets `$global:LASTEXITCODE = 0` and sets `$installVerifiable = $false`
(`:369-370`) so a silent installer failure is not reported as success. Failure scenario: DNS/TLS/CDN
compromise of `antigravity.google` yields code execution as the operator, outside every supervisor/broker
control, on a host that holds provider subscription credentials. Why it matters less than it looks: it is
the vendor's own documented install path and the file *says so*. Fix shape: pin a SHA-256 of the installer
in the repo and verify before `Invoke-Expression`, or drop the branch and print the command for the
operator to run.

**Census verdict:** this is an unusually clean codebase on this axis. No shell-string execution, no
deserialization gadget, no dynamic-name dispatch, no template SQL. The residual attack surface is not
in-process code injection — it is (a) the harness allow-list in §3g, (b) the argv-to-`cmd.exe` path the
lead already confirmed as R-14, and (c) S-06.

---
## §3 closure
Items 3a–3i above cover `.claude/settings.json` + `.claude/hooks/guard.py` in full (freeze-bypass
probes executed, network-denial bypasses enumerated). Two additions:
- `Bash(sqlite3:*)` (settings.json:59) is on the allow list with no path restriction — the governed
  SQLite store under `persistence/` is directly writable (append-only/CAS invariants 12/13 are
  enforced in the Python service layer, not by the DB), so the harness can edit governed memory
  out-of-band without touching a guarded tool. | LOW | [OBSERVED]
- `Bash(git stash:*)`, `Bash(git checkout:*)`, `Bash(git merge:*)` are allowed and can each **revert a
  frozen canonical file's content in the worktree** without a Write/Edit ever being issued. The freeze
  is a write-tool-path control, not a content invariant; only `tools/manifest/compute_manifest.py`
  re-derives the hashes, and nothing runs it automatically. | LOW | [OBSERVED]

---
## Â§1 docs/THREAT_MODEL.md â€” identifier-by-identifier mapping to code (main deliverable) â€” [OBSERVED]
`docs/THREAT_MODEL.md` (52 lines) names 6 trust boundaries (TB-1â€¦TB-6), 16 threats (T1â€¦T16),
9 failure modes, and 1 build-time analogue. Every one is mapped below against the live tree.

### Trust boundaries

| TB | Claim | Mitigation actually present (path:line) | Verdict |
|---|---|---|---|
| TB-1 | Operatorâ†”system is the only place authority enters; **text and voice converge on one command bus before the Permission Broker** | `voice_bridge/command_broker.py:92` `CommandBroker` is a single bus that accepts `source="voice"|"typed"` (`:43`). But **every actual caller is a voice path**: `adapters/voice_parakeet/adapter.py:17`, `control_plane/orchestration/conductor_voice_feed.py:396`, `control_plane/orchestration/operator_surface.py:42-46`. The operator's *typed* surface â€” the Electron IPC handlers â€” never touches it: `apps/desktop/main.js:1468` `pane:input` â†’ `manager.write(id,data)` goes straight to the ConPTY child, and `main.js:1521` `pane:close` â†’ `manager.kill(id)` executes a `kill` (a DESTRUCTIVE verb, `command_broker.py:25`) with **no** approval queue. | **PARTIAL / CONTRADICTED as written.** The bus exists and is well built, but convergence is not implemented: voice is strictly *more* restricted than typed. Fail-safe in direction, so not a vulnerability â€” but the document asserts a property the code does not have. |
| TB-2 | Only signed, schema-validated envelopes are control; terminal text never parsed as a command | **Implemented, both ends.** `control_plane/ipc/envelope.py:41-47` (HMAC-SHA256 + `hmac.compare_digest`), `:50-54` (Draft-7 schema validation with format checker), enforced at `control_plane/ipc/gateway.py:225` before `_dispatch` (`:229`). JS twin `apps/desktop/ipc/envelope.js`. Renderer has no `require` (`main.js:2406` `contextIsolation:true, nodeIntegration:false, sandbox:true`); zero `eval`/`new Function`/`JSON.parse` of PTY bytes in `apps/desktop/renderer/*.js` (Â§2 census). | **IMPLEMENTED** â€” strongest boundary in the tree. |
| TB-3 | Sovereignâ†”MCP: requests carry authenticated node identity+role+task+scope; MCP holds **no** authorization logic | `mcp_server/auth.py:13`, `memory_service.py:19`, `sovereign_tools.py:18` all *import* `SovereignPolicy` from `control_plane.policy`; no policy predicate is defined inside `mcp_server/`. Every write asks first: `memory_service.py:88,107,131` (`authorize_publish` / `authorize_transition` / `authorize_put_artifact`). | **IMPLEMENTED.** Caveat: separation is by *module*, not by trust â€” `mcp_server` imports `control_plane` directly, so a compromised MCP process holds the policy code in-memory and can call it with a forged `Identity`. |
| TB-4 | Harness config (`AGENTS.md`, MCP config, model output) is node-controlled untrusted input; enforcement lives outside the harness | Partly real: `adapters/frontier/codex.py:337`, `provider_cli_common.py:259` refuse/never-emit node-controlled instruction sources; `tests/unit/test_op12_frontier_adapters.py:184` asserts it. But "enforcement lives outside the harness (supervisor + broker + workspace isolation)" names three legs, of which the broker is voice-only (TB-1) and OS containment is unwired for interactive nodes (T3). | **PARTIAL** |
| TB-5 | Voiceâ†”command bus: transcripts are proposals, never executions | `command_broker.py:123-125` (voice + `confidence is None or < threshold` â†’ CLARIFY, fail-closed); `:25-29` verb sets; `voice_bridge/conductor_voice.py:187-189`. Prior reviewer verified the STT-confidence path and protected-verb matcher in depth. | **IMPLEMENTED** |
| TB-6 | Profile boundary: fail-closed loader; cloud adapter under `offline_airgapped` aborts startup with a logged violation | `control_plane/profiles/loader.py`; `control_plane/profiles/live_authorization.py:107,129,177,208-303` â€” 15 distinct fail-closed raises (version mismatch, non-bool flag, unknown register row, non-list providers, out-of-range `terminals_per_subscription`). | **IMPLEMENTED** |

### Threats T1â€“T16

| # | Claim | Mitigation actually present (path:line) | Verdict |
|---|---|---|---|
| T1 | Signed envelopes only (`message@1.0`); renderers never eval terminal output | `control_plane/ipc/envelope.py:41-54`, `gateway.py:225`; `schemas/message.schema.json`; renderer census clean | **IMPLEMENTED** |
| T2 | Sovereign policy never read from harness config; **adversarial tests** | Policy is never sourced from `AGENTS.md`/MCP config (`codex.py:337`, `provider_cli_common.py:259`). **But `tests/security/` contains only `.gitkeep`** (confirmed via `git ls-files`; directory otherwise empty) and no file under `tests/` matches `advers*|inject*|attack*|threat*`. Nearest real coverage: `tests/unit/test_op12_frontier_adapters.py:184` and the mutation harnesses in `tools/mutation/`. | **PARTIAL** â€” mechanism present; the named "adversarial tests" do not exist as a suite |
| T3 | Supervisor sandbox: **worktree ACL**, **deny-by-default egress**, **broker-mediated exec**; violations logged + node paused | (a) worktree: `node_runtime/workspace/worktree.py:88-128` + `binding.py` â€” a git-worktree-per-node convention plus a path-containment API, **not an OS ACL**; `containment.py:6-10` says so itself ("does NOT enforce filesystem or network denial at the OS layerâ€¦ until P10"). (b) deny-by-default egress: **absent** â€” no firewall/proxy/WFP code anywhere; `provider_cli_common.py:39-44,83-158` is explicit that the vendor `GROK_SANDBOX` flag is "an argument the harness itself honours", not containment. (c) broker-mediated exec: **absent for exec** â€” process launch is `main.js:1467` `pane:new` â†’ `createPaneWithSession` â†’ node-pty, with no broker in the path. | **PARTIAL â†’ mostly ABSENT** (1 of 3 named legs is real) |
| T3 (cont.) | *Known contradiction, adjudicated:* `JobObjectContainment` | **CONFIRMED and NARROWED.** `grep -rn JobObjectContainment` over the whole tree returns 4 live hits: the definition (`node_runtime/supervisor/containment.py:59`), its own `__enter__` (`:99`), and `tests/integration/test_node_runtime_mock_node.py:14,75`. **Zero product callers.** *But* a second, independently written Job-Object implementation `WindowsJob` (`adapters/frontier/process_tree.py:32-142`) **is** wired into product: `claude_code.py:43,460`; `provider_cli_common.py:1178,1201`; `adapters/voice_parakeet/wsl_parakeet.py:35,141`; `node_runtime/supervisor/provider_probe_session.py:88,529`. So OS process-tree containment exists â€” but only on the one-shot headless provider-CLI path. | **CONTRADICTED as a general claim; IMPLEMENTED on the probe path only** |
| T4 | Registration refused unless supervisor-spawned (`node@1.0`); **periodic process audit** | Refusal is real at two independent layers: `control_plane/nodes/registry.py:165-168` (`RegistrationRefused`, logged as `registration_refused`) and `adapters/base/contract.py:60-63` (`NakedLaunchRefused` raised in `BaseAdapter.__init__`, so no adapter subclass can be constructed naked), plus an adapter-enum allow-list at `registry.py:169-184` with no opt-out parameter. **The "periodic process audit" has no implementation** â€” no `process_audit`/`scan_processes`/`reconcile_processes` symbol exists anywhere. | **PARTIAL** (strong half implemented, second half absent) |
| T5 | Server-side lifecycle enforcement (`memory@1.0`); CANDIDATE quarantined; gates only path to ACCEPTED | `mcp_server/lifecycle.py:26-32` (explicit transition table), `:45-49` (`validate_status_transition` raises `IllegalStatusTransition`; `SUPERSEDED` requires a successor ref). Authority check at `memory_service.py:107` `authorize_transition`. | **IMPLEMENTED.** Narrow: the table at `:26` permits `CANDIDATE â†’ ACCEPTED` directly, so "gates are the only path to ACCEPTED" is enforced by `SovereignPolicy.authorize_transition`, not by the lifecycle table itself. |
| T6 | Immutable append + CAS + `conflict_record` objects | `persistence/store.py:187-205` `cas_advance_head` â€” `BEGIN IMMEDIATE`, compares `expected_head`, on mismatch `INSERT OR IGNORE INTO conflicts` and **does not overwrite**; `memory_service.py:91,119,125,154-158`; table DDL `store.py:91-95`. | **IMPLEMENTED** â€” the real thing, not a docstring |
| T7 | No policy in MCP; Sovereign-signed authorization; separate process; read/append capability only | Policy: see TB-3 â€” implemented. Separate process: `mcp_server/run_server.py` is spawned as a child, true in deployment. "Sovereign-**signed** authorization": the MCP path authenticates by bearer token + node identity (`mcp_server/auth.py`; `control_plane/ipc/gateway.py:47-71` `IpcCredentialStore.issue/verify/revoke`) â€” the HMAC signs the transport envelope, not the authorization grant. | **PARTIAL** (wording overclaims: token-bearer, not a signed grant) |
| T8 | Fail-closed node behavior (F5); local checkpoints (`checkpoint@1.0`); reconciliation before resume | `schemas/checkpoint.schema.json`; checkpoint use in `control_plane/recovery/succession.py`, `control_plane/policy.py`, `mcp_server/protocol.py`; `McpDisconnected` + fail-closed client per `mcp_server/__init__.py:5-6`. | **IMPLEMENTED (schema + recovery present)**; node-side hold/reconcile/resume loop not exercised â€” see Â§E |
| T9 | Confidence threshold; propose-never-execute; clarification; approval queue; transcript log | `command_broker.py:32` (`DEFAULT_CONFIDENCE_THRESHOLD = 0.6`), `:95,101-102`, `:123-125` â€” **`confidence is None` also clarifies**, i.e. fail-closed on a missing score; approval queue `control_plane/orchestration/operator_surface.py:283-319`. Verified in depth by the prior reviewer. | **IMPLEMENTED** |
| T10 | PTT/explicit trigger only; operator-presence assumption; protected actions always queued | `apps/desktop/renderer/mic.js:3` (push-to-talk capture); `main.js:2419-2445` â€” microphone is the **only** granted Electron permission, and a `media` request naming video is refused outright (`allowMedia`, `:2432-2437`), with both GRANT and DENY logged. Protected verbs `command_broker.py:27-28` â†’ `APPROVAL_QUEUED`. | **IMPLEMENTED** |
| T11 | Fail-closed profile loader aborts startup | `control_plane/profiles/live_authorization.py:107-303` (see TB-6) | **IMPLEMENTED** |
| T12 | Transcribe-then-discard; local-only TTL retention; zero egress offline (D-VOICE-04) | `adapters/voice_parakeet/adapter.py:6-7,34` (`diagnostic_retention: bool = False`, `retention_ttl_s = 7*24*3600`); `voice_bridge/conductor_voice.py:147-158,187-189,286`; cross-instance orphan purge at `main.js:1187-1196,2485`. Prior reviewer covered the on-disk persistence audit. | **IMPLEMENTED** |
| T13 | I-X3 governor in supervisor + status-bar visibility; raise only after R8 verification | `node_runtime/supervisor/subscription_governor.py:132` `SubscriptionGovernor`; release-before-acquire asserted at `control_plane/orchestration/live_succession.py:364-366`; read-only observability channel `control_plane/ipc/gateway.py:140-170`; status bar `apps/desktop/renderer/index.html:210` + `apps/desktop/statusbar/*`; allowance bounded to 1..2 at `live_authorization.py:303`. | **IMPLEMENTED** â€” one of the better-instrumented controls |
| T14 | CoWork silently modifies canonical files â†’ governed client class; canonical resources read-only to it; every access logged | **ABSENT.** `grep -rn -i cowork` over all `*.py`/`*.js` returns exactly **one** hit â€” a docstring aside at `control_plane/profiles/loader.py:7`. No governed CoWork client class, no read-only canonical resource binding, no per-access log. (`mcp_server/resources/` and `mcp_server/access_control/`, where such a thing would live, are `.gitkeep`-only empty packages.) | **ABSENT** |
| T15 | Staleness checklist before first assignment (F4 / Plan Â§19.1) | `control_plane/recovery/succession.py:10,54` `StalenessReport`, `:126-185` `reconstruct(...) -> (ConductorState, StalenessReport)` with integrity / directive-version / snapshot-age checks; live path `control_plane/orchestration/live_succession.py`. | **IMPLEMENTED** |
| T16 | Cost governor: per-debate budget, per-caller quota, global cap, hard â‰¤5 rounds | `debate_service/cost_governor/governor.py:34` `CostGovernor`; hard cap in `debate_service/round_manager/*.py:46` â€” `max_rounds = min(max_rounds, HARD_ROUND_CAP)`, **clamped regardless of the request** rather than merely validated. | **IMPLEMENTED** |

### Failure modes (THREAT_MODEL.md:38-45) â€” spot check
`Control-plane crash â†’ restart from SQLite WAL` : `persistence/store.py` uses SQLite with
`BEGIN IMMEDIATE` (`:196`); WAL mode not asserted in the file I read â€” **UNVERIFIED**.
`Node crash â†’ TERMINATED in registry, task back to READY` : `control_plane/nodes/states.py` +
`process_manager.py:75,177` â€” **INFERRED present**.
`Conductor loss â†’ succession (F4)` : `control_plane/recovery/succession.py` â€” **IMPLEMENTED**.
`WSL/Parakeet down â†’ voice surface disabled; text path unaffected` : `adapters/voice_parakeet/wsl_parakeet.py:360,420-427`
raises `VoiceEngineError` rather than degrading silently â€” **IMPLEMENTED**.
`GPU OOM â†’ residency planner evicts per policy` : `scheduler/residency_planner/` is a `.gitkeep`-only
**empty package** â€” **ABSENT** (offline profile only, so not load-bearing for the frontier path).
`Disk-full â†’ event-log write failure halts new writes fail-closed` : not exercised â€” **UNVERIFIED**.

### Build-time analogue (THREAT_MODEL.md:47-52)
Claim: "`.claude/settings.json` deny rules + `.claude/hooks/guard.py` hard-block writes outside the
project root, edits to `docs/canonical/`, and push/remote/network commands â€” enforcement by
configuration, not memory."

| Sub-claim | Reality (all executed, Â§3) | Verdict |
|---|---|---|
| hard-block writes outside the project root | True for `Write\|Edit\|MultiEdit\|NotebookEdit` (`guard.py:70-71` â†’ `check_path`); **dead code for Bash on Windows** (Â§3c: `../outside.txt`, `/c/Windows/...`, `D:\elsewhere\...` all ALLOW) | **PARTIAL / CONTRADICTED** |
| hard-block edits to `docs/canonical/` | True for the four write tools and unbypassable by 15 path tricks (Â§3a); **completely absent for Bash** (Â§3b: `echo evil > docs/canonical/<frozen>.md` â†’ ALLOW, with `Bash(cat:*)`/`Bash(python:*)` pre-approved) | **CONTRADICTED** |
| hard-block push/remote/network commands | `git push`/`git remote`/`curl`/`wget`/`ssh`/`scp`/`nc` denied by name; **`node:*`, `python:*`, `npx:*`, `npm install:*`, `pip install:*` all on the allow list** â€” each a full egress + arbitrary-code channel (Â§3g) | **CONTRADICTED** |
| "enforcement by configuration, not memory" | The configuration is a regex/prefix deny-list evadable by quoting, variable indirection and `git -c x=y push` (Â§3f); the hook **fails open** on four error paths (Â§3e) | **PARTIAL** |

### T-01 | MEDIUM | [OBSERVED] â€” THREAT_MODEL.md asserts five mitigations with no implementation
T2's "adversarial tests" (`tests/security/` is `.gitkeep`-only), T3's "deny-by-default egress"
(no OS/network control anywhere in the tree), T4's "periodic process audit" (no such symbol),
T14's entire row (one docstring mention of CoWork repo-wide), and the "residency planner"
failure mode (`scheduler/residency_planner/` empty). Failure scenario: an operator or auditor
reads this file to decide what is safe to run live and counts five shipped controls that do not
exist. Why it matters: it is the only threat-model artifact in the repo and it is cited by
`CLAUDE.md`-adjacent governance. Fix shape: add a `status` column (`implemented` / `scaffold` /
`deferred-to-P10`) â€” the honesty `node_runtime/supervisor/containment.py:6-10` already practices
about itself, applied to the document.

### T-02 | MEDIUM | [OBSERVED] â€” interactive nodes have no OS process-tree containment; invariant 29 holds only on the probe path
`JobObjectContainment` (`node_runtime/supervisor/containment.py:59`) has zero product callers.
The one that IS used, `WindowsJob` (`adapters/frontier/process_tree.py:32`), is reached only from
one-shot headless calls (`claude_code.py:460`, `provider_cli_common.py:1201`, `wsl_parakeet.py:141`,
`provider_probe_session.py:529`). The operator-facing panes â€” the ones running a real agentic CLI
for minutes at a time â€” are plain node-pty children (`apps/desktop/main.js:470`,
`terminal/conpty/session-manager`) with no job object, so `manager.kill(id)` (`main.js:1521`) and
the fail-closed `manager.killAll()` on supervision loss (`main.js:2309,2507`) kill the PTY, not the
descendant tree. Precondition: the harness spawns any detached/`start`-ed grandchild. Why it
matters: invariant 29 ("supervisor-level containment at the OS/process layer â€” never trust the
harness") names exactly the pane path, and that is the path without it. Fix shape: wrap
`SessionManager.spawn` in a per-pane job object; working code already exists twice in the tree.

### T-03 | LOW | [OBSERVED] â€” nine architecture-named packages are empty, including `control_plane/permissions/`
`mcp_server/{access_control,auth,conflict,events,provenance,resources,tools}`,
`control_plane/permissions/`, `debate_service/gate/`, `node_runtime/containment/`,
`scheduler/residency_planner/`, `tests/security/` are all `.gitkeep`-only (`git ls-files`); the real
code lives in flat sibling modules. Notably **there is no Permission Broker package at all** â€” the
only broker in the tree is `voice_bridge/command_broker.py`, which is the *voice* command broker.
Cosmetic in isolation, but it is what makes a directory-level skim of this repo overstate coverage:
`access_control/` and `permissions/` read as implemented boundaries and are empty.

### T-04 | LOW | [OBSERVED] â€” gateway `notify_*` family has no role gate (prior claim CONFIRMED)
`mcp_server/sovereign_tools.py:156,185,195,204,266` call `self.app.call("notify_message" /
"notify_debate" / "notify_debate_turn", â€¦)`. Unlike the publish paths at `:223-232` and `:270`
(which route through `_authorize(self.policy.authorize_publish_candidate/â€¦)`), none of the
`notify_*` calls consult `self.policy` or check `self.identity.role`. Any authenticated node of any
role can therefore inject a message/debate-turn notification. Impact is bounded â€” these are
notifications into the shell's observability surface, not memory writes â€” but it is the one tool
family in the file with no authority check, and the surface it feeds is the operator's own
situational-awareness display. Fix shape: gate `notify_*` on `authorize_debate_read`/role the same
way `list_debates` is gated (`sovereign_tools.py:378-381`).


---
## Â§4 Electron 31.7.7 advisory reachability triage â€” [OBSERVED]

Installed: `apps/desktop/node_modules/electron/package.json` â†’ **31.7.7**, declared `^31.0.0` as a
**devDependency** (`apps/desktop/package.json:23`). Start script is `electron .` (`:8`) â€” **unpackaged,
no ASAR, no electron-builder config, no code signing** anywhere in the tree.

### Configuration facts the triage rests on (all verified)
| Surface | Finding |
|---|---|
| CSP | `renderer/index.html:5` â€” `default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'`. **No `unsafe-eval`, no `unsafe-inline` for scripts, no remote origin.** No `connect-src`/`frame-src`/`form-action`/`navigate-to` (they inherit `default-src 'self'`, which does **not** constrain top-level navigation). |
| webPreferences | `main.js:2406` â€” `contextIsolation: true, nodeIntegration: false, sandbox: true`, preload `preload.js`. No `webSecurity:false`, no `allowRunningInsecureContent`, no `experimentalFeatures`, no `nodeIntegrationInSubFrames`, no `enableRemoteModule`, no `webviewTag` (defaults false in E31). |
| Content loaded | `main.js:2446` `win.loadFile(renderer/index.html)` only. **No remote URL is ever loaded**; the only external data entering the DOM is PTY bytes via xterm.js 5.5.0 and JSON models from main. |
| Permission handlers | `main.js:2442,2445` â€” **both** `setPermissionRequestHandler` and `setPermissionCheckHandler` installed; allow-list is microphone only, and a `media` request naming video is refused outright (`allowMedia:2432-2437`). Grants **and** denials logged. |
| `window.open` | **Never called.** Also **no `setWindowOpenHandler`** â€” Electron's default therefore still permits it. |
| navigation guards | **No `will-navigate` / `will-redirect` / `will-attach-webview` handler exists.** |
| custom protocol | **No** `protocol.register*` / `registerSchemesAsPrivileged` anywhere. |
| webview / iframe / offscreen | **None** â€” `grep` over `apps/desktop` returns zero `<webview>`, zero `<iframe>`, zero `offscreen`. |
| devtools | `openDevTools` never called. `Menu.setApplicationMenu` never called â†’ the **default menu remains**, so View â†’ Toggle DevTools is available to whoever is at the keyboard. `console-message`/`render-process-gone`/`did-fail-load` listeners are gated behind `process.env.SHELL_SELFCHECK` (`main.js:2450-2458`). |
| `setAsDefaultProtocolClient`, `setLoginItemSettings`, `shell.openPath`, `shell.openExternal`, `clipboard.*`, `dialog.*`, `requestSingleInstanceLock`/`second-instance`, `app.commandLine.appendSwitch` | **Zero occurrences repo-wide.** |
| contextBridge | Exactly one `exposeInMainWorld("sovereign", â€¦)` (`preload.js:12`), ~28 methods; objects cross the bridge **in both directions** (`newPane(spec)`, `spawnFromSelection(sel)`, `decideApproval(id,decision,reason)`, `probeVoice(opts)`). |

### Reachability table

| Advisory class (Electron/Chromium 31 rollup) | Reachable here? | Evidence / precondition |
|---|---|---|
| **Chromium/V8 renderer RCE** (heap UAF, type confusion, JIT) via **remote web content** | **NOT REACHABLE** | No remote content is ever loaded (`main.js:2446` `loadFile` only); CSP `default-src 'self'`; no webview/iframe. There is no browsing surface. |
| Same, via **locally rendered untrusted text** (PTY output through xterm.js, Skia/text-shaping/emoji bugs) | **RESIDUALLY REACHABLE (low)** | Model/CLI output is written into the DOM by xterm.js. A Chromium text-rendering or Blink DOM bug triggerable by attacker-chosen glyphs would be reachable. No such GHSA in the 32 was matched to this specifically â€” flag as the only live Chromium exposure. |
| **Context-isolation bypass** (e.g. GHSA-h7rp-cf8h-j98x, `Function.prototype.bind`) | **API IN USE â€” reachable only after prior renderer script execution; impact SEVERE if reached** | contextIsolation is the load-bearing control here (`main.js:2406`) and the preload bridge is rich (`preload.js:12-â€¦`). Bypassing it yields `ipcRenderer` â†’ see E-01: `pane:new` accepts an attacker-chosen executable. |
| **contextBridge prototype-pollution / setter advisories** (e.g. GHSA-ff2p-hmqr-hxm4) | **API IN USE â€” same precondition** | Objects cross the bridge both ways (`newPane(spec)`, `spawnFromSelection(sel)`); this is precisely the shape those advisories target. |
| **`window.open` named-target / new-window advisories** (e.g. GHSA-f3pv-wv63-48x8) | **NOT REACHABLE in normal operation; NOT MITIGATED if the renderer is compromised** | The app never calls `window.open`, but it also installs no `setWindowOpenHandler`, so the default (permit) stands. A one-line `setWindowOpenHandler(() => ({action:"deny"}))` would close the class outright. |
| **Navigation / redirect-based escapes** | **NOT MITIGATED** | No `will-navigate` handler; CSP `default-src` does not restrict top-level navigation. Renderer script could navigate the window to a remote origin, which would then be rendered by the vulnerable Chromium. Precondition is again renderer script execution. |
| **`<webview>` tag advisories** | **NOT REACHABLE** | `webviewTag` unset (false in E31); zero `<webview>` elements. |
| **Offscreen-rendering UAF** | **NOT REACHABLE** | `offscreen` never set. |
| **Custom-protocol / `registerFileProtocol` path-traversal advisories** | **NOT REACHABLE** | No protocol registration anywhere. |
| **`setAsDefaultProtocolClient` + `second-instance` argv-injection** (the classic Electron protocol-handler RCE) | **NOT REACHABLE** | Neither API used; no single-instance lock; no protocol registered. |
| **`shell.openExternal` / `shell.openPath` command-execution advisories** | **NOT REACHABLE** | Zero occurrences. |
| **`clipboard.readImage` / clipboard advisories** | **NOT REACHABLE** | Zero occurrences. |
| **DevTools-mediated advisories** | **OPERATOR-ONLY** | Never opened programmatically, but the default menu is left in place, so DevTools is one keystroke away for anyone at the console. |
| **ASAR integrity bypass / `app.getAppPath` advisories** | **N/A** | The app is unpackaged (`electron .`, no ASAR, no builder). See E-03 â€” the *reason* it is N/A is itself a weakness. |
| **`extract-zip` symlink traversal (the second HIGH)** | **DEV-TIME ONLY, NOT RUNTIME** | Reached through `@electron/get` when `npm install` unzips the Electron download. Preconditions: a malicious/MITM'd Electron zip. It cannot be triggered by running the app. |
| **`renderer command-line switch injection`** | **NOT REACHABLE** | `app.commandLine.appendSwitch` / `commandLine` appear **nowhere**; no untrusted data reaches Chromium's argv. |

### Upgrade-urgency verdict
Of the 32 rolled-up GHSAs, the classes this configuration actually exposes are **(a)** context-isolation
and contextBridge bypasses and **(b)** whatever Chromium bug a malicious glyph stream can reach â€” both of
which need a first foothold in the renderer that this app gives no obvious way to obtain (no remote
content, no eval, `script-src 'self'`, and the DOM sinks are almost entirely `esc()`-escaped, see E-02).
So the practical urgency of the semver-major jump to 43.4.0 is **moderate, not emergency** â€” *provided*
E-01 is fixed, because E-01 is what converts a renderer bug from "sandbox escape" into "host code
execution". Two zero-cost hardening steps buy most of the value without the ABI rebuild:
`setWindowOpenHandler(() => ({action:"deny"}))` and a `will-navigate` handler that cancels any
non-`file://` navigation.

### E-01 | HIGH | [OBSERVED] â€” the renderer chooses the executable and argv of every new pane
`apps/desktop/main.js:1467` `ipcMain.handle("pane:new", (_e, spec) => createPaneWithSession(sanitizeRendererSpec(spec)))`.
`sanitizeRendererSpec` (`main.js:488-496`) deletes **only** `env` and `cwd`. It does **not** touch
`spec.file` or `spec.args`, and `ptyFactory` (`main.js:469-485`) does
`pty.spawn(spec.file || "powershell.exe", spec.args || [], â€¦)` (`main.js:471,476`) with **no
executable allow-list anywhere** (`grep spec.file` â†’ 2 hits, both consumers). So
`window.sovereign.newPane({file:"cmd.exe", args:["/c","â€¦"]})`
spawns an arbitrary process. Worse, the process starts **before** admission:
`terminal/conpty/session-manager.js:69` calls `this._ptyFactory(spec)` and only reaches
`this._supervisor.admit(...)` at `:101` â€” the file's own comment at `:75-77` concedes "a denial still
created an OS process, and `kill()` is only intent". A refused spawn therefore still executed.
Failure scenario: any renderer-code-execution primitive (a Chromium/Electron 31 advisory, or a DOM XSS)
escalates directly to host code execution as the operator, bypassing the supervisor, the broker and the
permission profile entirely. The comment at `main.js:1463-1466` states the intended rule â€” "The renderer
â€¦ may NOT choose the child's environment or working directory" â€” and stops one field short of the one
that matters most. Fix shape: extend `sanitizeRendererSpec` to strip/allow-list `file` and `args` (an
ordinary operator pane needs neither), and move `admit()` in front of `_ptyFactory`.

### E-02 | LOW | [OBSERVED] â€” two `innerHTML` sinks skip `esc()`; the rest of the renderer is disciplined
`apps/desktop/renderer/renderer.js:456-461` (`rail.innerHTML`) interpolates `${c.id}` into a
`data-id="â€¦"` attribute and `${info.title || c.id}` into element text **unescaped**; `:499-500`
(`min.innerHTML`) does the same with `${m.id}` / `${m.title || m.id}`. Every other sink in the file â€”
the whole inspector (`:632-687`), approvals (`:719-779`), picker (`:857-905`), status bar (`:819`) â€”
routes untrusted strings through `esc()` (`:607`). Pane titles come from `main.js:504`
(`spec.title || spec.file`, renderer-supplied â‡’ self-only) and from `main.js:619`
`CONDUCTOR Â· ${label}` where `label` is `conductorModelLabel()` â†’ `main.js:1867 model_label: o.label`,
i.e. a **host model name enumerated by the picker**. So a locally installed model whose name contains
markup lands in an unescaped sink. Precondition: the operator installs/pulls a model with an
attacker-chosen name, and the pane is collapsed to the rail or minimized. Combined with E-01 the impact
would be host code execution; alone it is a rendering defect. Note `esc()` (`:607`) escapes `& < > "`
but **not `'`** â€” safe today because every attribute in the file is double-quoted, but it is a landmine
for the next template. Fix shape: `esc()` those four interpolations and add `'` to the escape map.

### E-03 | INFO | [OBSERVED] â€” the shell runs unpackaged and unsigned from the working tree
`apps/desktop/package.json:8` `"start": "electron ."`, no `build`/`electron-builder` block, no ASAR, no
signing. This is why the ASAR-integrity advisory class is N/A â€” but it also means anything that can write
a file under `apps/desktop/` (including the build harness itself, per Â§3g: `Bash(python:*)` and
`Bash(node:*)` are pre-approved and `guard.py` has no Bash write containment on Windows) owns the next
`npm start`. Also note `electron` is a **devDependency**, which is correct for a source-run app but means
there is no reproducible artifact for an operator to verify.


---
# FINAL SECTIONS (area security2)

> **Correction to T-04 above (supersedes it).** After reading `mcp_server/collaboration_service.py`
> I must narrow my own finding: `notify_*` has no gate *of its own*, but it is **not independently
> invocable**. Each call is emitted only after an authorized write â€”
> `collaboration_service.py:179 authorize_send_message`, `:206,211 authorize_debate/open_debate`,
> `:238 authorize_debate_turn`, each through `_require` (`:104`) which raises on a deny. So a node
> cannot emit a notification it was not already permitted to cause. **T-04 downgraded to INFO.**

## A. Adjudication of prior claims

| Prior ID | Verdict | Evidence (path:line) | Notes |
|---|---|---|---|
| `JobObjectContainment` has ZERO product callers | **CONFIRM, then NARROW** | `node_runtime/supervisor/containment.py:59`; only other refs are `tests/integration/test_node_runtime_mock_node.py:14,75` | The *capability* is not absent: a second Job-Object impl, `WindowsJob` (`adapters/frontier/process_tree.py:32`), IS in product â€” `claude_code.py:460`, `provider_cli_common.py:1201`, `wsl_parakeet.py:141`, `provider_probe_session.py:529`. The real gap is that it covers only headless one-shot calls, never the interactive node-pty panes (`main.js:470`). See T-02. |
| No product mechanism prevents a conductor answering for itself after an MCP dispatch failure | **NOT ADJUDICATED here** â€” outside the four items I was given; `control_plane/orchestration/conductor_dispatch.py` and invariant 18 (`no node solely judges its own work`) are the relevant surfaces. Recorded as open in Â§E. | â€” | â€” |
| Gateway `notify_*` family has no role gate | **NARROW** | `mcp_server/sovereign_tools.py:156,185,195,204,266` (ungated) vs `mcp_server/collaboration_service.py:104,179,206,211,238` (the preceding write IS gated) | True literally, immaterial in practice â€” the notification is a side-effect of an already-authorized write, not a callable surface. INFO. |
| (lead, R-16) Electron 31.7.7 carries 32 GHSAs; several match this app's shape | **NARROW** | Â§4 table | Of the four the lead named: `window.open` (GHSA-f3pv-wv63-48x8) â†’ app never calls it *and* installs no `setWindowOpenHandler`; contextBridge setters (GHSA-ff2p-hmqr-hxm4) â†’ API heavily used, reachable only post-compromise; context-isolation bypass (GHSA-h7rp-cf8h-j98x) â†’ same; renderer switch injection â†’ **not reachable**, `app.commandLine` appears nowhere. Upgrade urgency is moderate, not emergency â€” *conditional on fixing E-01*. |
| (lead, R-14) cmd.exe injection executes on host through quoted args | **BUILDS ON** | E-01 | E-01 is the renderer-side analogue: `pane:new` lets the renderer pick `file` and `args` outright, no quoting subtlety needed. |
| `.claude/hooks/guard.py` freeze protection is bypassable | **REFUTE for `check_path`; CONFIRM for the harness as a whole** | Â§3a (15 path tricks, all DENY) vs Â§3b (Bash branch never calls `check_path`) | The function is solid; the wiring is not. |

## B. New findings (consolidated index)

| ID | Sev | Conf | Title |
|---|---|---|---|
| **E-01** | **HIGH** | [OBSERVED] | Renderer chooses the executable and argv of every new pane (`main.js:1467,488-496,469-485`); the PTY starts *before* supervisor admission (`session-manager.js:69` vs `:101`) |
| S-01 | HIGH | [OBSERVED] | The `docs/canonical/` freeze is not applied to the Bash tool at all (`guard.py:70-88`) |
| T-01 | MEDIUM | [OBSERVED] | THREAT_MODEL.md asserts five mitigations with no implementation (T2 adversarial tests, T3 deny-by-default egress, T4 periodic process audit, T14 entire row, residency planner) |
| T-02 | MEDIUM | [OBSERVED] | Interactive nodes have no OS process-tree containment; invariant 29 holds only on the probe path |
| S-02 | MEDIUM | [OBSERVED] | Bash "redirect outside project root" check is dead code on Windows (`guard.py:77-88`) |
| S-03 | MEDIUM | [OBSERVED] | guard.py resolves relative paths against PROJECT_ROOT, the tool against cwd (`guard.py:49-50`) |
| S-04 | MEDIUM | [OBSERVED] | guard.py fails OPEN on four error paths (`guard.py:52-54,66-67,75`; `settings.json:71,80`) |
| S-05 | MEDIUM | [OBSERVED] | BASH_BLOCK regexes trivially evadable and simultaneously over-blocking |
| T-03 | LOW | [OBSERVED] | Nine architecture-named packages are empty, incl. `control_plane/permissions/` â€” there is no Permission Broker package at all |
| E-02 | LOW | [OBSERVED] | Two `innerHTML` sinks skip `esc()` (`renderer.js:456-461,499-500`); `esc()` (`:607`) does not escape `'` |
| S-06 | LOW | [OBSERVED] | Unpinned remote installer `Invoke-Expression (Invoke-RestMethod â€¦)` (`run_frontier_providers.ps1:371`) â€” the only RCE-shaped path, disclosed and gated |
| S-07 | LOW | [OBSERVED] | `Bash(sqlite3:*)` allows out-of-band edits to the governed store; `git stash/checkout/merge` can revert a frozen canonical file without a Write/Edit (Â§3 closure) |
| E-03 | INFO | [OBSERVED] | Shell runs unpackaged and unsigned from the working tree |
| T-04 | INFO | [OBSERVED] | `notify_*` has no gate of its own (side-effect of an authorized write) |

## C. What I executed

- `grep`/`ripgrep` census over `**/*.py|js|mjs|cjs|ps1|psm1` excluding `node_modules` for the full
  dangerous-call pattern set (Â§2). Result: zero `eval`/`exec`/`pickle`/`yaml.load`/`os.system`/
  `shell=True` in Python; zero `new Function`/`vm.runIn*`/`child_process.exec(`/`execSync(` shell-string
  form in product JS; one `Invoke-Expression` (`run_frontier_providers.ps1:371`).
- `py -3.12` AST-free scan of `apps/desktop/renderer/renderer.js` enumerating every `${â€¦}` template
  interpolation and flagging those not wrapped in `esc()` â†’ 100+ hits triaged by hand against their
  sink (`innerHTML` vs `textContent`); only two land unescaped in an `innerHTML` sink.
- `git ls-files` to prove which packages are `.gitkeep`-only (nine).
- `grep -rn JobObjectContainment` tree-wide â†’ 4 live hits, none in product.
- Read in full: `docs/THREAT_MODEL.md`, `apps/desktop/preload.js`, `apps/desktop/renderer/index.html`,
  `control_plane/ipc/envelope.py`, `voice_bridge/command_broker.py` (head), plus targeted ranges of
  `apps/desktop/main.js` (462-505, 1462-1530, 2380-2470), `terminal/conpty/session-manager.js` (56-130),
  `mcp_server/{lifecycle,memory_service,sovereign_tools,collaboration_service,__init__}.py`,
  `control_plane/nodes/registry.py`, `adapters/base/contract.py`, `adapters/frontier/process_tree.py`,
  `persistence/store.py`, `tools/providers/run_frontier_providers.ps1` (330-400).
- (from the earlier half of this report) `scratchpad/security2/probe_guard.py` â€” imported the REAL
  `guard.py` and drove `check_path()`/`main()` with ~30 synthetic payloads including real NTFS junctions
  created in `%TEMP%`. **No repo file was written, no canonical file was touched, no provider CLI ran,
  no Electron process was started.**

## D. What is genuinely strong here

- **TB-2 / T1 is real and end-to-end.** `control_plane/ipc/envelope.py:41-47` computes HMAC-SHA256 over a
  canonical payload and verifies with `hmac.compare_digest`; `gateway.py:225` refuses before dispatch;
  a byte-compatible JS twin exists (`apps/desktop/ipc/envelope.js`). Both structural *and* integrity
  checks must pass. This is the rare case where the docstring under-sells the code.
- **The dangerous-call census is clean to a degree I did not expect.** Zero shell-string execution, zero
  deserialization gadgets, zero dynamic-name dispatch, zero template SQL across ~2900 lines of
  `main.js` plus the whole Python tree. `mcp_server/__init__.py:21-37` is an allow-list lazy importer,
  not a name-to-module concatenation. `process_manager.py:59` carries its own `noqa: S603` justification.
- **The naked-launch refusal is defense-in-depth, not a single check.** `registry.py:165-168` refuses
  registration *and* `adapters/base/contract.py:60-63` refuses construction in `BaseAdapter.__init__`,
  so no adapter subclass can exist without a supervisor context â€” plus an adapter-enum allow-list at
  `registry.py:169-184` whose bypass parameter was deliberately removed (U227).
- **CAS + conflict records are implemented, not described.** `persistence/store.py:187-205` uses
  `BEGIN IMMEDIATE`, compares the expected head, and on mismatch writes a conflict row and leaves the
  head alone. Invariant 13 ("never silent last-write-wins") is enforced in SQL, not in prose.
- **The Electron permission model is tighter than most production apps.** Both the request *and* check
  handlers are installed (`main.js:2442,2445`), the allow-list is one capability, a `media` request
  naming video is refused outright rather than partially satisfied, and grants are logged as loudly as
  denials. `contextIsolation`+`sandbox`+`nodeIntegration:false` with a `script-src 'self'` CSP and no
  remote content is the correct baseline.
- **`guard.py:check_path` withstood every path trick I could construct** â€” dot-dot bounce, mixed case,
  8.3, `\\?\`/`\\.\` prefixes, ADS, trailing dot/space, UNC admin share, GLOBALROOT, and two real NTFS
  junctions. The function is not the weakness; its wiring is.

## E. Not covered / open questions

1. **The conductor self-answer question was not adjudicated.** It fell outside my four items;
   `control_plane/orchestration/conductor_dispatch.py` + invariant 18 are where to look.
2. **Whether `E-01` is exploitable end-to-end** â€” I did not run Electron (forbidden), so the
   `newPane({file,args})` path is [OBSERVED] by code reading and by `channel-sweep.js:79` (which drives
   `newPane` with a `{title}` spec through the real bridge), not by execution. A one-line `node --test`
   against `sanitizeRendererSpec` would settle it without Electron.
3. **Disk-full fail-closed** (`THREAT_MODEL.md:44`) and **node-side hold/reconcile/resume** (T8) were
   not exercised.
4. **`npm audit` was not re-run** (no network / no install); I relied on the lead's R-16 result and
   triaged reachability from configuration only.

**Two items I opened and closed while writing Â§E, recorded so they are not re-opened:**
- *SQLite WAL* (`THREAT_MODEL.md:40`) â€” **IMPLEMENTED**: `persistence/store.py:60`
  `conn.execute("PRAGMA journal_mode=WAL")`, negotiated after a busy-timeout so a sibling schema
  transaction is waited on rather than raced (`:57`).
- *Can PTY output set a pane title?* â€” **No.** There is no `onTitleChange`/OSC-title handler anywhere
  in `apps/desktop`; `renderer.js:149` paints `info.title` from the `shell:state` model only, and that
  title is set in main at `main.js:504,619` from the spec or the conductor label. So **E-02 is
  operator-reachable only (a maliciously named host model), not model-reachable** â€” its LOW severity
  holds.
- *`.claude/settings.local.json`* â€” read; it contains only
  `{"enabledMcpjsonServers":["sovereign"],"enableAllProjectMcpServers":true}`. It **adds no permission
  rules**, so Â§3's analysis of the tracked `settings.json` is complete. Note `enableAllProjectMcpServers:true`
  means any `.mcp.json` server the repo gains is auto-enabled without a prompt â€” a supply-chain edge
  worth knowing, but no such server beyond `sovereign` exists today.

