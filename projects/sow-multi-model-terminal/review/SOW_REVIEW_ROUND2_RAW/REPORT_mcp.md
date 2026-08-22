# REPORT_mcp — scoped review of mcp_server/, persistence/, debate_service/, schemas/
(incremental; started 2026-08-16)

## Working notes (code-read pass, before execution)

### R-13 (stdin unbounded / publish_artifact unbounded)
- [OBSERVED] mcp_server/sovereign_tools.py:519 `for line in sys.stdin:` — no length cap; contrast mcp_server/server.py:86 `max_line = 8*1024*1024` and :93-97 which refuses >8MB. CONFIRM the asymmetry.
- [OBSERVED] `_publish_artifact` :408-415: only checks `isinstance(content, str)`; forwards `content.encode("utf-8")` straight to `memory.put_artifact` -> `cas.put` (persistence/cas.py:36-44) with no size bound. `task_id` is `args.get("task_id")` — passed to put_artifact_meta as opaque metadata; NEVER looked up in operational_tasks. TOOLS schema :474 marks task_id required but inputSchema is never validated at runtime (handle_request :496-505 calls runtime.call directly; there is no jsonschema.validate of inputSchema anywhere in sovereign_tools.py). So publish_artifact accepts task_id="" / missing / "t-nonexistent". CONFIRM R-59.
- Preconditions: caller must already hold a valid SOVEREIGN_CONTROL_TOKEN (identity resolves via gateway); the write is bounded only by disk. The gateway itself caps HTTP bodies at 1 MiB (apps/desktop/control/sovereign-control-server.js:6 MAX_BODY) — but publish_artifact never touches the gateway (store-only), so that cap does not apply. Execution below.

### R-28 (publish_synthesis debate gate outside the fence; record_synthesis has none)
- [OBSERVED] sovereign_tools.py:272-273: `task = get_task(...)`; `_considered_debates(...)` runs BEFORE `memory.put_artifact` (:294) and BEFORE `record_synthesis` (:300). `_considered_debates` :384 reads `list_debates` on the reading connection — outside any BEGIN IMMEDIATE.
- [OBSERVED] collaboration_service.py:380-426 `record_synthesis.apply` checks candidates/bindings only; no read of operational_debates. Docstring at :64-74 and :322-329 admits it (U410).
- Race window: a worker `open_debate` (fenced create at store.py:403-423) that commits between :273 and :300 leaves the task COMPLETED with an OPEN debate; the synthesis record's debate_ids omits it. Precondition: a worker (any owner) may open a debate on the task (authorize_open_debate: participants subset of task participants, >=2) — so this is reachable by a worker racing the conductor. CONFIRM. Severity moderate: it violates the tool's own stated gate but not authority.

### R-29 (operational tables not schema-validated; task@1.0 incompatible)
- [OBSERVED] `jsonschema.validate` in persistence/store.py only at :150 (append_memory_version), :239 (commit_version), :520 (_make_conflict). create_operational_task/mutate_operational_task/append_operational_message/create_operational_debate/mutate_operational_debate (:308-460) validate nothing; they persist `json.dumps(task)` as-is.
- [OBSERVED] schemas/task.schema.json requires `capability_req` + `state` enum PENDING..DONE with additionalProperties:false; operational task (collaboration_service.py:122-130) has `status` ASSIGNED.., `objective`, `owner_node_ids`, `thread_id` — zero overlap beyond task_id. Also task_id pattern `^t-...` — operational ids are `t-<hex>` (ok) BUT create_task accepts a caller-supplied `task_id` (:113,:120) with no pattern check (not exposed via the tool, only direct callers). CONFIRM. Note CLAUDE.md says "JSON Schemas in schemas/ are the single source of truth; every envelope pins its schema version" — operational task/message/debate rows carry NO `schema` field at all (collaboration_service.py:122-130, :180-187, :218-226).

### R-30 (budget_units never read; CostGovernor/DebateService unreachable; max_rounds 1..5)
- [OBSERVED] `budget_units` written at collaboration_service.py:223; no reader in mcp_server/ or persistence/. post_debate_turn.apply (:243-261) enforces only round_no <= max_rounds. CONFIRM budget is decorative on the tool path.
- [OBSERVED] max_rounds 1..5 enforced :212-213 (service) AND TOOLS schema :470 (advisory only). CONFIRM.
- [OBSERVED] debate_service/service.py DebateService.request_debate is not imported by sovereign_tools.py / collaboration_service.py; CostGovernor not referenced in mcp_server/. CONFIRM unreachable from the 16 tools. Invariant 17 (cost-governed debate) is therefore only satisfied by round-count on the live path.

### R-58 (CAS temp filename fixed per digest, no fsync)
- [OBSERVED] persistence/cas.py:41-43: `tmp = path.with_suffix(".tmp")` — path is `<root>/ab/<62hex>` so tmp = `<root>/ab/<62hex>.tmp`, deterministic per digest; two processes putting the same content concurrently both write the same tmp then `tmp.replace(path)`; on Windows the second `replace` after the first already moved it raises FileNotFoundError (tmp gone) -> put() raises even though the blob is present. No fsync before rename. CONFIRM both. get() re-verifies :46-49 so a torn blob is detected on read (fail closed) — narrows to availability, not integrity.
- Nuance: put() :38-39 short-circuits on `path.exists()` — race only matters for the FIRST publish of identical bytes by two nodes at once. LOW.

### R-78 empty scaffold dirs
- [OBSERVED] mcp_server/{access_control,auth,conflict,events,provenance,resources,tools}/ and debate_service/gate/ are empty directories. `mcp_server/auth/` (dir) sits beside `mcp_server/auth.py` — regular module wins over namespace package so imports work today; any file dropped into auth/ silently changes resolution. CONFIRM as INFO.

### R-86 non-reentrant write lock across caller-supplied mutator
- [OBSERVED] store.py:48 `threading.Lock()` (not RLock); mutate_operational_task :352-377 and mutate_operational_debate :434-460 invoke `mutator(current)` while holding it. Live mutators (collaboration_service.py apply closures) call only `self._policy.*` and `_now()` — no store calls. CONFIRM hazard, NARROW to latent (no live deadlock path). LOW.

### Invariant 7 — literal role strings in mcp_server/
- see grep below. Python side: no role literal decides anything in mcp_server/. The DIVERGENT copy is apps/desktop/control/application-control.js:12-16 `requireControlRole` with literals "conductor"/"worker"/"operator" (spawn_worker/stop_worker/preflight/assign_task = conductor-only; list_models/get_worker_status = conductor|worker|operator; notify_* ungated). It does not consult control_plane.policy (U345 acknowledged in collaboration_service.py:8-9 docstring).

### Worker reachability of publish_synthesis / open_debate / abort_debate / spawn_worker
- publish_synthesis: worker -> sovereign_tools.py:270 authorize_publish_synthesis -> policy.py:366-370 denies. BLOCKED at MCP. Not a gateway op.
- abort_debate: worker -> collaboration_service.py:332 authorize_debate_abort -> denied. BLOCKED. Not a gateway op.
- open_debate: worker ALLOWED (authorize_debate: worker in four-role set; authorize_open_debate: participants subset of task participants and >=2 — creator counts). Then notify_debate via gateway: application-control.js:314-320 checks only `debate.opened_by_node_id === identity.node_id` — no role gate, no store cross-check.
- spawn_worker: gateway requireControlRole "conductor" (:207) -> worker BLOCKED at gateway; MCP forwards blindly (:98). OK.
- NEW: gateway notify_message (:293-312) / notify_debate (:314-320) / notify_debate_turn (:322-328) accept the payload as-is: recipients/participants come from the POST body, nothing is checked against the store, only sender/opener/turn node_id must equal the caller. A worker holding its own SOVEREIGN_CONTROL_TOKEN can therefore POST notify_message directly (no MCP, no policy) with arbitrary recipient_node_ids and any task_id, and io.notifyNode types a prompt into ANY pane incl. the conductor's. authorize_send_message's cross-task recipient rule exists only on the Python path.

### Tool matrix (validates / forwards / store-only)
| tool | runtime validation | gateway op | store write | refreshes _lastSeen |
|---|---|---|---|---|
| list_models | none | list_models | no | yes |
| spawn_worker | none in py; gateway checks provider/model/role | spawn_worker | no | yes |
| stop_worker | none | stop_worker | no | yes |
| get_worker_status | none | get_worker_status | reads tasks | yes |
| assign_task | policy task_create; objective/owners nonempty | preflight_assignment, assign_task | task+assignment msg | yes |
| send_message | kind enum, body, recipients, policy | notify_message | message | yes |
| read_messages | policy filters | none | no | NO |
| publish_progress | status enum, policy update | notify_message | task+message | yes |
| open_debate | policy, rounds 1..5, budget>=1, proposition | notify_debate | debate | yes |
| post_debate_turn | policy, OPEN, body, round ceiling (in fence) | notify_debate_turn | debate+message | yes |
| close_debate | policy, OPEN, decision, quorum (in fence) | none | debate | NO |
| abort_debate | policy, OPEN, reason | none | debate | NO |
| publish_artifact | content is str ONLY | none | CAS+meta | NO |
| read_artifact | policy read + project meta | none | no | NO |
| publish_candidate | policy, provider/model match, lists, refs exist | notify_message | CAS+meta+task+message | yes |
| publish_synthesis | policy, debate gate, contributions, narrative fields | none | CAS+meta+task | NO |
- `arguments` are never validated against inputSchema in Python (handle_request :496-505); every handler uses `.get(..., default)`, so `additionalProperties:false` and `required` in TOOLS are advisory to the client only. publish_progress with status missing defaults to IN_PROGRESS silently.

## Execution results (probe.py / probeE.py in scratchpad/mcp; stub gateway = http.server on 127.0.0.1; SOVEREIGN_STORE_ROOT=scratch; PYTHONDONTWRITEBYTECODE=1 so no __pycache__ lands in the repo)

Session A (conductor identity, PYTHONUTF8=1 in child env — set ONLY so replies are parseable; the product does NOT set it):
- initialize OK, tools/list = 16 tools.
- publish_artifact with 2 MiB content and task_id "t-does-not-exist": SUCCESS in 0.02 s; CAS blob written (2,097,152 bytes) under scratch store; meta task_id="t-does-not-exist". [OBSERVED] R-13/R-59 CONFIRMED: no size bound, task_id not checked for existence.
- publish_artifact with NO task_id and an unknown key `bogus_key`: SUCCESS, meta task_id=null. [OBSERVED] inputSchema `required`/`additionalProperties:false` NOT enforced server-side.
- spawn_worker with `{}` arguments: forwarded verbatim to the gateway (stub returned {}); Python did no validation. [OBSERVED]
- 8 MiB garbage line (`{xxxx…`): process replied -32700 with id null and stayed alive; ping afterwards OK. [OBSERVED] So the missing bound is a memory bound only (line buffered whole before json.loads), not a crash.
- utf-8 round trip with PYTHONUTF8=1: 'café Á č — 😀' stored+read intact.
- publish_synthesis on unknown task: "CollaborationError: no such task in this project" — read check precedes everything.

Session B (conductor identity, host-default encoding — how .mcp.json / .codex/config.toml launch it: `py -3.12 -m mcp_server.sovereign_tools`, no PYTHONUTF8/PYTHONIOENCODING anywhere in apps/desktop or the CLI configs):
- `py -3.12 -c` with piped stdio reports: stdin cp1252/surrogateescape, stdout cp1252/surrogateescape. [OBSERVED]
- publish_artifact content "a — b" (UTF-8 bytes 61 20 E2 80 94 20 62): stored CAS bytes = `a \xc3\xa2\xe2\x82\xac\xe2\x80\x9d b` (mojibake "a â€” b", 11 bytes vs 7) → DIFFERENT content hash than the client's bytes; read_artifact returns the mojibake. [OBSERVED] NEW: the stdin leg is ALSO cp1252 — every non-ASCII character a CLI sends is decoded as cp1252 (+surrogateescape) before it reaches json.loads, so bodies of messages/turns/tasks/candidates and artifact contents are persisted corrupted, and content hashes no longer match what the node believes it published.
- publish_artifact content "Á" (C3 81; 0x81 undefined in cp1252 → surrogate U+DC81): tool call fails "UnicodeEncodeError: 'utf-8' codec can't encode character '\udc81'… surrogates not allowed" (isError:true); process stays alive; ping OK. [OBSERVED] Any text containing a UTF-8 byte in {81,8D,8F,90,9D} (e.g. Á, č, ď, ě, ř, ő, and many CJK/emoji sequences) makes send_message/post_debate_turn/publish_candidate/publish_artifact FAIL on this host, because every store write path ends in `.encode("utf-8")` or json.dumps→sqlite (sqlite3 would also raise on lone surrogates).

Session C (worker identity, same MCP):
- publish_synthesis → "ToolError: only conductor/operator may publish synthesis" (policy). BLOCKED.
- abort_debate on unknown id → "no such debate" (read check first; abort role check would follow).
- assign_task → gateway `preflight_assignment` was called FIRST (stub saw it), THEN policy refused "only the conductor/operator may create assignments". [OBSERVED] Ordering: sovereign_tools.py:129 asks the JS gateway before control_plane.policy (:132). In the real gateway a worker is refused by requireControlRole("conductor") at application-control.js:255 and that refusal is what the worker hears, and it is recorded by _recordOperation as a failed op — the JS literal-role copy is the first authority consulted for assign_task.
- publish_artifact with task_id "" → SUCCESS (worker can write arbitrary CAS blobs with empty task_id).
- spawn_worker / stop_worker → forwarded to gateway (stub ok). In the real gateway requireControlRole("conductor") refuses (application-control.js:207, :246). Python side has NO gate; the only gate is the JS literal.

D (R-58 concurrent identical put, 8 threads, in-process): 1/8 raised `PermissionError(13, 'The process cannot access the file because it is being used by another process')` — Windows flavour of the shared-tmp race (a second writer opened `<digest>.tmp` while the first was renaming it). Blob present afterwards. [OBSERVED] CONFIRM R-58 (availability: a legitimate publish can fail spuriously; caller retry would succeed via the exists() short-circuit).

E (invariant 9 write side, in-process MemoryService+SovereignPolicy):
- worker w1 publishes tier=private_node → conductor c1 and worker w2 `get_head_entry` → DENIED "readable only by its author". Read isolation holds (policy).
- conductor c1 `transition(private entry) → UNDER_REVIEW` → APPLIED (ref @2). gate g1 `→ ACCEPTED` → APPLIED (ref @3). [OBSERVED] `authorize_transition` (control_plane/policy.py:126-146) never consults `tier`; a directing/gate node can rewrite the lifecycle status of another node's PRIVATE-tier entry it is not allowed to read. `list_by_status` remains shared-only by query shape (store.py:181) so the promoted private entry does not surface there — but its head/version chain is mutated by a non-author. Reachability today: only via mcp_server/server.py `transition` op (not one of the 16 stdio tools).
- publish with tier="bogus" → StoreError from memory@1.0 enum. Tier values ARE schema-enforced.

---
# FINAL REPORT — area: mcp (mcp_server/, persistence/, debate_service/, schemas/)
Tree: D:\multi model terminal app\sovereign-orchestration-workspace @ bad029e7. All repo access read-only; every run used PYTHONDONTWRITEBYTECODE=1 and a scratch SOVEREIGN_STORE_ROOT.

### A. Adjudication of prior claims
| Prior ID | Verdict | Evidence (path:line) | Notes |
|---|---|---|---|
| R-13 stdin unbounded vs server.py 8 MB | CONFIRM (narrowed to memory, not crash) | sovereign_tools.py:519 `for line in sys.stdin` (no cap); server.py:86,93-97 caps at 8 MiB | [OBSERVED] 8 MiB garbage line → -32700 reply, process alive. Bound is only process RAM. Precondition: the client is the CLI the operator launched. LOW. |
| R-59 publish_artifact unbounded / any task_id | CONFIRM | sovereign_tools.py:408-415; memory_service.py:126-140; cas.py:36-44 | [OBSERVED] 2 MiB blob written in 0.02 s with task_id "t-does-not-exist"; also with NO task_id + unknown key (meta.task_id=null). No size cap; task existence never checked; the gateway's 1 MiB MAX_BODY (sovereign-control-server.js:6) does not apply because publish_artifact is store-only. Worker identity can do the same with task_id "". |
| R-28 synthesis debate gate outside fence; record_synthesis has none | CONFIRM + WIDEN | sovereign_tools.py:272-273 vs :294,:300; collaboration_service.py:380-426 (no debate read) | [OBSERVED] Not only a race: open_debate has no task-status guard (collaboration_service.py:199-230), so a worker can open a debate on a COMPLETED/synthesized task at any time (probeF #9 shows worker-opened debate); record_synthesis has no "already synthesized" guard either → conductor re-publish overwrites `synthesis` in place. |
| R-29 operational tables not schema-validated; task@1.0 incompatible | CONFIRM | store.py: only :150,:239,:520 validate; :308-460 none. schemas/task.schema.json requires capability_req/state(PENDING..DONE), additionalProperties:false vs collaboration_service.py:122-130 shape | [OBSERVED] message@1.0 (msg_id/from_node/to/auth/integrity) and debate@1.0 (debate_id/request) are equally disjoint from operational message/debate rows. Operational rows carry no `schema` field at all. artifact meta happens to validate against artifact@1.0 (checked with jsonschema) but is never validated at runtime. |
| R-30 budget_units never read; CostGovernor/DebateService unreachable; max_rounds 1..5 | CONFIRM | collaboration_service.py:214-215,:223 (write only); :253-255 (round ceiling only); debate_service/service.py not imported by mcp_server/* | [OBSERVED] Invariant 17 on the live tool path = round count only. |
| R-58 CAS fixed tmp name, no fsync; get() re-verifies | CONFIRM | cas.py:41-43,:46-49 | [OBSERVED] 8 concurrent puts of identical bytes: 1 raised `PermissionError(13 … being used by another process)` (Windows flavour). Blob intact; get() would detect a torn blob. Availability only, first-publish-of-identical-bytes only (exists() short-circuit :38). LOW. |
| R-78 empty scaffold dirs | CONFIRM (INFO) | mcp_server/{access_control,auth,conflict,events,provenance,resources,tools}/, debate_service/gate/ empty | `mcp_server/auth/` dir shadows nothing today (regular module auth.py wins over a namespace pkg) but is a resolution trap. |
| R-86 non-reentrant lock across mutator | CONFIRM, NARROW to latent | store.py:48 Lock; :352-377,:434-460 call mutator under lock | Live mutators (collaboration_service.py apply closures) call only policy/_now(); sovereign_tools is single-threaded. No live deadlock path. LOW. |
| Invariant 7 (role decisions delegate to control_plane.policy) | CONFIRM for Python; DIVERGENT copy in JS | grep: zero role literals in mcp_server/*.py, persistence/*, debate_service/*; apps/desktop/control/application-control.js:12-16,:172,:207,:246,:255,:331 | JS `requireControlRole` literals gate spawn/stop/preflight/assign (conductor) and list_models/get_worker_status (conductor|worker|operator); notify_* ungated. It never consults control_plane.policy. For assign_task the JS copy is asked FIRST (sovereign_tools.py:129 before :132) — a worker hears the JS refusal, not the policy's. |
| Worker → publish_synthesis / abort_debate | REFUTE reachability | sovereign_tools.py:270 → policy.py:366-370; collaboration_service.py:332 → policy.py:329-333 | [OBSERVED] worker publish_synthesis → "only conductor/operator may publish synthesis". Neither is a gateway op. |
| Worker → open_debate | CONFIRM reachable (by design, I-DS1) | policy.py:149-160,:264-276 | Worker may open a debate naming itself + the task creator (creator ∈ _task_participants). Then notify_debate at the gateway is role-ungated. |
| Worker → spawn_worker via MCP / gateway | REFUTE (gateway blocks) | sovereign_tools.py:98 forwards blindly; application-control.js:207 requireControlRole conductor | [OBSERVED] Python forwards a worker's spawn_worker/stop_worker to the gateway; the ONLY gate is the JS literal. |
| notify_* no role gate (lead) | CONFIRM + SHARPEN | application-control.js:293-328 | See B-2: no store cross-check, recipients from payload → prompt injection into any pane. |

### B. New findings

**B-1 | HIGH | [OBSERVED] | stdin leg of the stdio MCP is ALSO cp1252 (+surrogateescape): non-ASCII content is persisted corrupted, content hashes are of the mojibake, and publish_artifact fails outright for common characters**
- Where: sovereign_tools.py:519 (`for line in sys.stdin`) — text-mode stdin under the host locale; `py -3.12` with piped stdio reports `cp1252 surrogateescape` both directions. Nothing in .mcp.json, .codex/config.toml, apps/desktop sets PYTHONUTF8/PYTHONIOENCODING.
- Measured (Session B, no PYTHONUTF8): publish_artifact "a — b" (E2 80 94) → CAS bytes `61 20 C3 A2 E2 82 AC E2 80 9D 20 62` ("a â€” b"), size 11 vs 7, DIFFERENT sha256 than the client's bytes; publish_artifact "Á" (C3 81, 0x81 undefined in cp1252 → U+DC81) → `UnicodeEncodeError … surrogates not allowed` isError:true (sovereign_tools.py:413 strict encode). Any text containing UTF-8 bytes 81/8D/8F/90/9D (Á, č, ě, ř, ő, ď … many CJK/emoji sequences) fails publish_artifact; every other write path (send_message/post_debate_turn/publish_progress/candidate/synthesis) persists surrogate-escaped mojibake in sqlite/CAS (json.dumps ensure_ascii escapes it, probeF #10). Wire replies to the SAME cp1252 process happen to round-trip byte-for-byte (surrogateescape symmetric), which hides the corruption from the calling CLI while the durable store, content hashes, the gateway-forwarded `latest_progress` text (pane chrome) and any UTF-8 reader see garbage. Complements the lead's stdout finding (F2): the whole boundary is locale-encoded. Only stdio test (apps/desktop/test/sovereign-mcp-stdio.test.js:20-46) tolerates it (Node readline replaces invalid bytes; assertions never touch descriptions); tests/unit/test_sovereign_tools_protocol_e2e.py never spawns the process (no Popen) so `main()` has zero encoding coverage.
- Fix shape: in `main()` reconfigure `sys.stdin`/`sys.stdout` to `encoding="utf-8", errors="strict"` (or read `sys.stdin.buffer` and write `sys.stdout.buffer`), plus one subprocess test that sends "Á" and asserts stored bytes == C3 81.

**B-2 | HIGH | [OBSERVED code / INFERRED effect] | Gateway notify_message / notify_debate / notify_debate_turn accept store-unverified payloads → any token-holder (incl. a worker) can inject prompts into ANY live pane**
- Where: application-control.js:293-312 (checks only `message.sender_node_id === identity.node_id`), :314-320 (`debate.opened_by_node_id`), :322-328 (`turn.node_id`); recipients/participants come straight from the POST body and are fed to `io.notifyNode(nodeId, prompt)`. No role gate, no lookup of message/debate in the store, no policy call. On the Python path `authorize_send_message` (policy.py:212-226) restricts recipients to task participants — but a node's SOVEREIGN_CONTROL_TOKEN is in its own env, so a worker CLI (or anything running in that pane) can POST /v1/tools/call {operation:"notify_message", arguments:{message:{sender_node_id:<self>, task_id:"anything", message_id:"x", recipient_node_ids:["<conductor>", "<other worker>"]}}} and the gateway types the notice into those panes. Also `notify_debate` proposition is embedded verbatim in the prompt (:316) — free text into the conductor pane, reachable even through MCP by a worker via open_debate.
- Precondition: token in hand (it is, for every governed node). Fix shape: gateway verifies message/debate ids against the store (or Python passes only ids and the gateway rehydrates), and enforces recipients ⊆ task participants via the same policy.

**B-3 | MEDIUM | [OBSERVED] | Operational task status has no legality machine and no terminal state — a worker can COMPLETE/CANCEL/regress a shared task; candidates and synthesis can be rewritten in place after synthesis**
- Where: collaboration_service.py:138-160 update_task (any status in TASK_STATES from any state; authorize_task_update == read rule, policy.py:191-206); record_candidate :350-378 (no status guard, `candidates[node]=candidate` overwrite); record_synthesis :380-426 (no "already synthesized" guard); store.py:345-377 UPDATE-in-place.
- Measured (probeF): worker w1 → COMPLETED on a fresh task; → CANCELLED while w2 still working; after conductor synthesis (COMPLETED, bound to hash c4c1d61…) w1 re-published a candidate → task back to CANDIDATE_READY with candidates[w1] = 6be67fb… while `synthesis.contributions` still binds c4c1d61… (stale binding, invariant 13/16 territory); w2 then set IN_PROGRESS on the synthesized task. operational_tasks holds 1 row: prior states are gone (only messages are append-only) — invariant 12 "immutable append-only history" is not what the operational tables do; the store docstring (store.py:1-12) scopes immutability to memory versions only.
- Gateway effect (application-control.js:167-171): a worker's self-reported COMPLETED/CANCELLED clears its deadlines and flips it READY. Fix shape: an operational task state machine mirroring mcp_server/lifecycle.py (terminal COMPLETED/CANCELLED/FAILED; CANDIDATE_READY→COMPLETED only via record_synthesis; worker-settable subset), and refuse record_candidate/record_synthesis on terminal tasks.

**B-4 | MEDIUM | [OBSERVED] | Invariant 9 tier isolation is read-side only: a conductor/gate can transition (and a gate promote) another node's private_node memory entry it may not read**
- Where: policy.py:126-146 authorize_transition never reads `tier`; memory_service.py:96-125 transition does no read authorization before `get_entry`. Measured (probeE): w1 private_node entry → conductor read DENIED, conductor transition → UNDER_REVIEW APPLIED (@2), gate → ACCEPTED APPLIED (@3). list_by_status stays shared-only (store.py:181) so it does not surface, but the private chain is mutated by non-authors. Isolation is by policy+query shape (convention), not store partitioning: `store.get_entry/get_head` are identity-free. Reachability: mcp_server/server.py `transition` op only (not one of the 16 stdio tools). Fix shape: `authorize_transition` denies non-author on non-shared tiers.

**B-5 | MEDIUM | [OBSERVED] | Identity is resolved once at startup and never re-checked for store-only tools — revocation is invisible to read_messages/read_artifact/publish_artifact/close_debate/abort_debate/publish_synthesis**
- Where: sovereign_tools.py:83-85 (one `identity()` call), store-only handlers never call `self.app`. Gateway revokes on stop (sovereign-control-server.js:108,:232). Precondition: the Python child outlives its credential (R-61 measured 15 s teardown; any orphaned MCP child). Same six tools never stamp `_lastSeen`, so a node that only reads/closes looks "silent" to connectionState (sovereign-control-server.js:126-160). Fix shape: re-validate identity on every call (cheap loopback) or a TTL.

**B-6 | LOW | [OBSERVED] | inputSchema is advisory only — no server-side validation of tool arguments; several list fields stored unshaped**
- handle_request :496-505 never validates against TOOLS[].inputSchema; handlers `.get(...)` with defaults. Measured: publish_artifact with no task_id + unknown key OK; spawn_worker `{}` forwarded to gateway; publish_progress without status silently IN_PROGRESS. close_debate stores `agreements=[{'not':'a string'},5]`, `unresolved_points="abc"`→['a','b','c'] (collaboration_service.py:284,:305-306 `list(x or [])`); open_debate/send_message evidence_refs/artifact_refs, create_task constraints/acceptance_criteria/peer_nodes, publish_progress blockers/questions likewise unvalidated. Fix: one jsonschema.validate(args, inputSchema) in runtime.call; `_strings(nonempty=False)` at the six list sites.

**B-7 | LOW | [OBSERVED] | Two transports, three credential systems, one bound present in one and absent in the other**
- mcp_server/server.py (loopback, CredentialStore auth.py) is NOT launched by the desktop (main.js:437 spawns run_gateway with no --mcp-port → EchoControlSurface); it is used by tools/live/run_15d_*_smoke.py, control_plane/orchestration/live_flow.py, tests. Not dead, but a second product-adjacent server with its own auth store beside the JS gateway tokens and IpcCredentialStore. It shares SovereignPolicy (no duplicated policy) but its 8 MiB line bound, `errors="replace"` decode and put_artifact `application/octet-stream` default diverge from sovereign_tools (no bound, locale decode, `text/plain; charset=utf-8`).

**B-8 | INFO | [OBSERVED] | SQLite hygiene** — journal_mode=WAL after busy_timeout (store.py:59-60, correct order; connect timeout 30 s :55); PRAGMA journal_mode return value unchecked; foreign_keys=ON with no FKs; no explicit wal_checkpoint (autocheckpoint default; last closer checkpoints); executescript only for DDL under the process lock (:69, no open txn); all SQL parameterized (no f-string/format); no schema-version table (CREATE IF NOT EXISTS cannot migrate); operational_tasks.task_id / operational_debates.debate_id are GLOBAL primary keys (:108,:130) so a caller-supplied id colliding across projects errors "already exists" (existence leak; only via direct create_task task_id=, not the tool).

**B-9 | INFO | [OBSERVED] | N-01 follow-up — other unencoded text boundaries in mcp_server/persistence/debate_service:** none besides the two stdio legs (sovereign_tools.py:519 read, :529 write; :516 stderr). All open()/read_text use encoding="utf-8" (store.py:26, debate_service/service.py:29-30); server.py:101 decodes with explicit utf-8/replace; protocol.py:36,:55 explicit; run_server.py prints ASCII only; tools/live/emit_operational_state.py:48 uses json.dumps default ensure_ascii → ASCII-safe. No subprocess/text=True in scope.

**B-10 | INFO | [OBSERVED] | Partial-write surfaces:** send_message/publish_progress/publish_candidate persist first then call the gateway; a gateway failure returns isError with the row already committed (only assign_task handles this, sovereign_tools.py:139-145). post_debate_turn commits the turn then sends the message outside the fence (collaboration_service.py:263-270).

### C. What you executed
- `py -3.12 -m pytest tests/unit/test_operational_write_path.py tests/unit/test_sovereign_tools_protocol_e2e.py tests/unit/test_collaboration_policy_delegation.py -q -p no:cacheprovider` (PYTHONDONTWRITEBYTECODE=1) → **101 passed in 3.16 s**.
- scratchpad/mcp/probe.py: stub gateway (http.server, POST /v1/tools/call; identity→{n1,conductor,p} or {w1,worker,p}; else {ok:true,result:{}}) + real `py -3.12 -m mcp_server.sovereign_tools` child, cwd=repo, SOVEREIGN_STORE_ROOT=scratch. Session A (PYTHONUTF8=1, set by me only to parse replies): 16 tools; 2 MiB publish_artifact ok (blob 2,097,152 B); no-task_id ok; spawn_worker {} forwarded; 8 MiB garbage → -32700, alive; utf-8 round-trip intact. Session B (host default): stdin cp1252/surrogateescape; em-dash stored as 11-byte mojibake; "Á" → UnicodeEncodeError isError. Session C (worker): synthesis denied; assign_task hits gateway preflight before policy; publish_artifact task_id "" ok; spawn/stop forwarded. D: 8-thread identical CAS put → 1 PermissionError. probeE.py: private_node transition/promote by non-author APPLIED. probeF.py: worker COMPLETED/CANCELLED; post-synthesis candidate overwrite; status regress; close_debate unshaped lists; worker-opened debate; lone surrogate persisted.
- `echo '{}' | py -3.12 -c "import sys;print(sys.stdin.encoding, sys.stdin.errors, sys.stdout.encoding, sys.stdout.errors)"` → `cp1252 surrogateescape | cp1252 surrogateescape`.
- greps: role literals in scope (none), open()/subprocess/encode boundaries, executescript/format SQL, MCPServer launch sites, PYTHONUTF8 in configs.

### D. What is genuinely strong in this area
- Every role/scope decision on the Python side really is delegated: zero role literals in mcp_server/*, persistence/*, debate_service/*; `_require`/`_authorize` are the only verdict→refusal sites (collaboration_service.py:103-108, sovereign_tools.py:223-227), and the policy is a constructor-injected dependency (sovereign_tools.py:77-90) so it is falsifiable.
- The write fence is real: BEGIN IMMEDIATE + process lock, mutator re-reads inside the transaction, identity guard on task_id/project_id/debate.task_id (store.py:345-377,:425-460), and the round ceiling / close quorum / candidate completeness / contribution-hash binding are computed on the in-fence row (collaboration_service.py:243-261,:286-311,:394-424) — probeF #4 shows the binding refuses drift at write time.
- CAS refs strictly validated (cas.py:14,:26-32) → no path traversal; get() re-hashes on read; artifact reads are project-scoped through metadata (memory_service.py:150-160) so knowing a hash is not enough.
- Fail-closed error envelope: every tool exception becomes isError:true and the process keeps serving (sovereign_tools.py:502-505); malformed lines return -32700 without dying (measured with 8 MiB).
- `_considered_debates` (sovereign_tools.py:384-406) is a well-built two-directional gate (open blocks, foreign refused, unnamed closed refused, aborted reported separately); `_contributions` likewise refuses invented and dropped work by node id.

### E. Not covered / open questions
- Did not run apps/desktop node tests or the real SovereignControlServer (JS) — B-2 is code-read + Python-side confirmation only; a JS-side probe posting notify_message with foreign recipients would make it [OBSERVED].
- Did not measure memory growth for a multi-GB single stdin line (R-13); 8 MiB only.
- Did not audit control_plane/policy.py beyond the entry points mcp_server calls; U350 (conductor aborting a debate it argues in) left as the repo records it.
- Whether Claude/Codex CLIs ever set PYTHONUTF8 for MCP children (would mask B-1 for that vendor only) — unverified; the repo's own configs do not.
- debate_service/round_manager, cost_governor, evidence_manager internals not reviewed line-by-line (unreachable from the 16 tools; only import/wiring checked).
