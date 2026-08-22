from __future__ import annotations

from pathlib import Path

import pytest

from control_plane.policy import Identity, SovereignPolicy
from mcp_server.collaboration_service import CollaborationError, CollaborationService
from mcp_server.sovereign_tools import handle_request
from persistence import SovereignStore


@pytest.fixture()
def service(tmp_path: Path):
    store = SovereignStore(tmp_path / "sovereign.db")
    svc = CollaborationService(store, SovereignPolicy())
    yield svc
    store.close()


def identities():
    return (
        Identity("cond-1", "conductor", "proj"),
        Identity("gemini-1", "worker", "proj"),
        Identity("grok-1", "worker", "proj"),
    )


def assigned(service: CollaborationService):
    cond, gemini, grok = identities()
    task = service.create_task(
        cond, objective="independently find integration risks",
        owner_node_ids=[gemini.node_id, grok.node_id], peer_nodes=[gemini.node_id, grok.node_id],
        acceptance_criteria=["publish three risks", "exchange one direct question"],
    )
    return cond, gemini, grok, task


def test_conductor_worker_and_peer_messages_are_persisted_and_scoped(service: CollaborationService) -> None:
    cond, gemini, grok, task = assigned(service)
    first = service.read_messages(cond, task_id=task["task_id"], include_all=True)
    assert first[0]["message_kind"] == "assignment"
    question = service.send_message(
        gemini, task_id=task["task_id"], thread_id=task["thread_id"],
        recipient_node_ids=[grok.node_id], message_kind="question",
        body="Which runtime boundary looks weakest?", evidence_refs=["m-evidence"],
    )
    reply = service.send_message(
        grok, task_id=task["task_id"], thread_id=task["thread_id"],
        recipient_node_ids=[gemini.node_id, cond.node_id], message_kind="answer",
        body="The terminal-to-MCP bridge.", reply_to=question["message_id"],
    )
    visible = service.read_messages(gemini, task_id=task["task_id"])
    assert [m["message_id"] for m in visible][-2:] == [question["message_id"], reply["message_id"]]
    assert service.read_messages(cond, task_id=task["task_id"], include_all=True)[-1]["reply_to"] == question["message_id"]


def test_progress_lifecycle_and_cross_task_access_fail_closed(service: CollaborationService) -> None:
    cond, gemini, grok, task = assigned(service)
    updated = service.update_task(
        gemini, task_id=task["task_id"], status="IN_PROGRESS",
        progress={"completed": "mapped runtime", "what_remains": "rank gaps"},
    )
    assert updated["status"] == "IN_PROGRESS"
    stranger = Identity("worker-other", "worker", "proj")
    with pytest.raises(CollaborationError, match="cross-task"):
        service.get_task(stranger, task["task_id"])
    with pytest.raises(CollaborationError, match="cross-task recipient"):
        service.send_message(
            gemini, task_id=task["task_id"], thread_id=task["thread_id"],
            recipient_node_ids=[stranger.node_id], message_kind="question", body="leak?",
        )


def test_bounded_debate_preserves_evidence_and_dissent(service: CollaborationService) -> None:
    cond, gemini, grok, task = assigned(service)
    debate = service.open_debate(
        cond, task_id=task["task_id"], proposition="MCP connectivity is the top risk",
        participant_node_ids=[gemini.node_id, grok.node_id], evidence_refs=["m-1"], max_rounds=1,
    )
    turn = service.post_debate_turn(
        gemini, debate_id=debate["debate_id"], body="Agree, because nodes lack a callable bridge.",
        evidence_refs=["m-2"],
    )
    service.post_debate_turn(
        grok, debate_id=debate["debate_id"], body="Challenge: readiness is a larger risk.",
        evidence_refs=["m-3"], reply_to=turn["turn_id"],
    )
    with pytest.raises(CollaborationError, match="round limit"):
        service.post_debate_turn(gemini, debate_id=debate["debate_id"], body="second round")
    closed = service.close_debate(
        cond, debate_id=debate["debate_id"], decision="Both are coupled launch risks.",
        agreements=["live connections require readiness"], dissent=["which gap ranks first"],
    )
    assert closed["state"] == "CLOSED"
    assert closed["dissent"] == ["which gap ranks first"]
    assert closed["turns"][0]["evidence_refs"] == ["m-2"]
    assert closed["closure_reason"] == "Both are coupled launch risks."
    assert set(closed["claims"]) == {
        "Agree, because nodes lack a callable bridge.", "Challenge: readiness is a larger risk.",
    }


def test_debate_cannot_close_without_both_participants(service: CollaborationService) -> None:
    cond, gemini, grok, task = assigned(service)
    debate = service.open_debate(
        cond, task_id=task["task_id"], proposition="readiness outranks persistence",
        participant_node_ids=[gemini.node_id, grok.node_id], max_rounds=2,
    )
    service.post_debate_turn(gemini, debate_id=debate["debate_id"], body="readiness first")
    with pytest.raises(CollaborationError, match="every participant"):
        service.close_debate(cond, debate_id=debate["debate_id"], decision="premature")


def _candidate(node_id: str, artifact: str = "sha256:candidate") -> dict:
    return {
        "task_id": "set by caller", "worker_node_id": node_id, "provider": "provider",
        "model": "model", "summary": "ranked risks", "claims": ["risk one"],
        "evidence_refs": ["file.py:1"], "peer_messages_considered": [],
        "debates_considered": [], "limitations": [], "status": "CANDIDATE",
        "artifact_ref": artifact, "content_hash": artifact,
    }


def test_two_candidate_records_survive_and_gate_synthesis(service: CollaborationService) -> None:
    cond, gemini, grok, task = assigned(service)
    with pytest.raises(CollaborationError, match="every worker"):
        service.record_synthesis(cond, task_id=task["task_id"], synthesis={"status": "SYNTHESIS"})
    first = service.record_candidate(gemini, task_id=task["task_id"],
                                     candidate=_candidate(gemini.node_id, "sha256:gemini"))
    assert first["status"] == "IN_PROGRESS"
    second = service.record_candidate(grok, task_id=task["task_id"],
                                      candidate=_candidate(grok.node_id, "sha256:grok"))
    assert second["status"] == "CANDIDATE_READY"
    assert set(second["candidates"]) == {gemini.node_id, grok.node_id}
    # W-16: this call used to omit `contribution_bindings` and still COMPLETE, which is the defect
    # itself -- a synthesis that proved nothing about which candidates it was built from. The
    # property this test asserts (synthesis completes once every worker has published) is unchanged;
    # it now has to state its contributions, exactly as the product caller already does
    # (sovereign_tools.py:302).
    completed = service.record_synthesis(
        cond, task_id=task["task_id"], synthesis={"status": "SYNTHESIS", "artifact_ref": "sha256:s"},
        contribution_bindings=[
            {"node_id": gemini.node_id, "candidate_content_hash": "sha256:gemini"},
            {"node_id": grok.node_id, "candidate_content_hash": "sha256:grok"},
        ])
    assert completed["status"] == "COMPLETED"
    # …and the canonical record now names them, which is what "prove which candidates it used" means
    assert completed["synthesis"]["candidate_node_ids"] == sorted([gemini.node_id, grok.node_id])


def test_candidate_without_artifact_reference_is_refused(service: CollaborationService) -> None:
    _cond, gemini, _grok, task = assigned(service)
    candidate = _candidate(gemini.node_id, "")
    with pytest.raises(CollaborationError, match="artifact_ref"):
        service.record_candidate(gemini, task_id=task["task_id"], candidate=candidate)


def test_standard_mcp_lists_exact_operational_tools_and_returns_structured_results() -> None:
    class Runtime:
        def call(self, name, args):
            return {"called": name, "arguments": args}

    listed = handle_request(Runtime(), {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    required = {
        "list_models", "spawn_worker", "stop_worker", "assign_task", "get_worker_status",
        "send_message", "read_messages", "open_debate", "post_debate_turn", "close_debate",
        "publish_artifact", "read_artifact", "publish_candidate", "publish_synthesis",
    }
    assert required.issubset(names)
    called = handle_request(Runtime(), {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                        "params": {"name": "spawn_worker",
                                                   "arguments": {"provider": "grok_build"}}})
    assert called["result"]["structuredContent"]["called"] == "spawn_worker"
    assert called["result"]["isError"] is False


# ---- W-16: publication-time synthesis integrity was OPT-IN --------------------------------------
# `record_synthesis` declared `contribution_bindings: list[dict] | None = None` and gated the
# candidate/hash binding validation on `if contribution_bindings is not None`. The only PRODUCT
# caller (sovereign_tools.py:302) does supply it -- so the invariant was enforced by CALLER
# CONVENTION, not by the state-mutating service. Anything else reaching the service directly
# published a synthesis that named no candidates and bound no content hashes.
#
# Precision, so nobody re-reads this and concludes the finding was wrong: the "candidates from every
# worker" check above it IS unconditional and always was. It is specifically the HASH-BINDING half
# that was optional.
#
# This is DISTINCT from W-05. W-16 is "a synthesis must prove which candidates it used". W-05 is
# "those candidates cannot mutate underneath it afterwards" (operator ruling D-5: candidate freeze).

def test_a_synthesis_that_states_no_contributions_is_refused_inside_the_fence(
        service: CollaborationService) -> None:
    """W-16 NEGATIVE. Reaching the service directly, with both candidates committed, must not
    publish a synthesis that proves nothing about which candidates it used."""
    cond, gemini, grok, task = assigned(service)
    service.record_candidate(gemini, task_id=task["task_id"],
                             candidate=_candidate(gemini.node_id, "sha256:gemini"))
    service.record_candidate(grok, task_id=task["task_id"],
                             candidate=_candidate(grok.node_id, "sha256:grok"))
    with pytest.raises(CollaborationError, match="contribution"):
        service.record_synthesis(cond, task_id=task["task_id"],
                                 synthesis={"status": "SYNTHESIS", "artifact_ref": "sha256:s"})
    # …and the task must NOT have advanced: a refused publication leaves the row where it was.
    row = service.get_task(cond, task["task_id"]) if hasattr(service, "get_task") else None
    if row is not None:
        assert row["status"] != "COMPLETED"


def test_a_synthesis_bound_to_a_stale_candidate_hash_is_still_refused(
        service: CollaborationService) -> None:
    """The binding validation itself must keep working once it is no longer optional."""
    cond, gemini, grok, task = assigned(service)
    service.record_candidate(gemini, task_id=task["task_id"],
                             candidate=_candidate(gemini.node_id, "sha256:gemini"))
    service.record_candidate(grok, task_id=task["task_id"],
                             candidate=_candidate(grok.node_id, "sha256:grok"))
    with pytest.raises(CollaborationError, match="content_hash"):
        service.record_synthesis(
            cond, task_id=task["task_id"],
            synthesis={"status": "SYNTHESIS", "artifact_ref": "sha256:s"},
            contribution_bindings=[
                {"node_id": gemini.node_id, "candidate_content_hash": "sha256:STALE"},
                {"node_id": grok.node_id, "candidate_content_hash": "sha256:grok"},
            ])


# ---- W-05: no operational state machine; candidates mutated after synthesis ---------------------
# `update_task` validated `status in TASK_STATES` -- SET MEMBERSHIP, not transition legality -- and
# `record_candidate` / `record_synthesis` set the status directly inside their OWN applies, so
# nothing anywhere asked whether a transition was legal. Reproduced: a worker drove a shared task
# COMPLETED -> CANCELLED -> IN_PROGRESS, then rewrote its candidate after synthesis; the task
# regressed to CANDIDATE_READY and the stored synthesis was left binding a content hash that no
# longer existed.
#
# W-16 closed the OTHER half ("a synthesis must prove which candidates it used"). This is
# post-publication stability: those candidates cannot mutate underneath an accepted synthesis.
#
# Operator ruling D-5: CANDIDATE FREEZE. Once a candidate revision has participated in a committed
# synthesis it is immutable and an overwrite is REFUSED. Synthesis invalidation is NOT built.

def _completed(service: CollaborationService):
    """Drive the ordinary lifecycle all the way to a committed synthesis."""
    cond, gemini, grok, task = assigned(service)
    tid = task["task_id"]
    service.record_candidate(gemini, task_id=tid,
                             candidate=_candidate(gemini.node_id, "sha256:gemini"))
    service.record_candidate(grok, task_id=tid,
                             candidate=_candidate(grok.node_id, "sha256:grok"))
    completed = service.record_synthesis(
        cond, task_id=tid, synthesis={"status": "SYNTHESIS", "artifact_ref": "sha256:s"},
        contribution_bindings=[
            {"node_id": gemini.node_id, "candidate_content_hash": "sha256:gemini"},
            {"node_id": grok.node_id, "candidate_content_hash": "sha256:grok"},
        ])
    assert completed["status"] == "COMPLETED"
    return cond, gemini, grok, tid, completed


def test_the_ordinary_lifecycle_still_runs_end_to_end(service: CollaborationService) -> None:
    """W-05 POSITIVE. ASSIGNED -> IN_PROGRESS -> CANDIDATE_READY -> COMPLETED must still succeed."""
    cond, gemini, grok, task = assigned(service)
    tid = task["task_id"]
    assert task["status"] == "ASSIGNED"
    assert service.update_task(gemini, task_id=tid, status="IN_PROGRESS")["status"] == "IN_PROGRESS"
    service.record_candidate(gemini, task_id=tid,
                             candidate=_candidate(gemini.node_id, "sha256:gemini"))
    second = service.record_candidate(grok, task_id=tid,
                                      candidate=_candidate(grok.node_id, "sha256:grok"))
    assert second["status"] == "CANDIDATE_READY"
    completed = service.record_synthesis(
        cond, task_id=tid, synthesis={"status": "SYNTHESIS", "artifact_ref": "sha256:s"},
        contribution_bindings=[
            {"node_id": gemini.node_id, "candidate_content_hash": "sha256:gemini"},
            {"node_id": grok.node_id, "candidate_content_hash": "sha256:grok"},
        ])
    assert completed["status"] == "COMPLETED"


def test_a_terminal_status_has_no_outbound_transition(service: CollaborationService) -> None:
    """W-05 NEGATIVE (a). COMPLETED is terminal. The reproduced escape was COMPLETED -> CANCELLED,
    which membership validation happily allowed because CANCELLED is a member of TASK_STATES."""
    cond, _gemini, _grok, tid, _row = _completed(service)
    with pytest.raises(CollaborationError, match="transition"):
        service.update_task(cond, task_id=tid, status="CANCELLED")
    with pytest.raises(CollaborationError, match="transition"):
        service.update_task(cond, task_id=tid, status="IN_PROGRESS")


def test_a_worker_cannot_regress_a_completed_task(service: CollaborationService) -> None:
    """W-05 NEGATIVE (b). The reproduction was driven by a WORKER on a shared task, so the refusal
    has to hold for the owner-worker too, not only for a stranger."""
    _cond, gemini, _grok, tid, _row = _completed(service)
    with pytest.raises(CollaborationError):
        service.update_task(gemini, task_id=tid, status="IN_PROGRESS")


def test_a_candidate_that_a_synthesis_cites_cannot_be_rewritten(
        service: CollaborationService) -> None:
    """W-05 NEGATIVE (c), under D-5. The overwrite FAILS OUTRIGHT -- no synthesis invalidation --
    and the stored synthesis never ends up binding a content hash that no longer exists."""
    _cond, gemini, _grok, tid, completed = _completed(service)
    bound = {c["node_id"]: c["candidate_content_hash"]
             for c in completed["synthesis"]["contributions"]}
    assert bound[gemini.node_id] == "sha256:gemini"

    # Match the FREEZE's own reason, not merely "something refused". The transition table also
    # refuses this call (COMPLETED is terminal), so a bare `raises(CollaborationError)` passes with
    # the freeze deleted — the mutation harness demonstrated exactly that, row W05b surviving. D-5
    # is a rule about the CANDIDATE REVISION, not about the task's status, and it has to be graded
    # on its own terms or it is guarded only by a coincidence that a later legal edge would remove.
    with pytest.raises(CollaborationError, match="frozen"):
        service.record_candidate(gemini, task_id=tid,
                                 candidate=_candidate(gemini.node_id, "sha256:REWRITTEN"))

    after = service.get_task(gemini, tid)
    assert after["status"] == "COMPLETED", "a refused rewrite must not regress the task"
    assert after["candidates"][gemini.node_id]["content_hash"] == "sha256:gemini"
    # the invariant this whole unit exists for: the synthesis still cites a hash that IS on the row
    for row in after["synthesis"]["contributions"]:
        assert (after["candidates"][row["node_id"]]["content_hash"]
                == row["candidate_content_hash"])


# ---- W-59 / U410: the synthesis debate gate belongs at the state transition ----------------------
# U410: `record_synthesis` enforced only the completeness rule and would move the task to COMPLETED
# while a debate on it was still OPEN — the 19.5 validator's probe P2 did exactly that through the
# service and got 'COMPLETED' back. The U332 gate (`_considered_debates`) guards the TOOL path
# only, so invariant 16 was enforced at the boundary, not at the transition — the U326 shape: the
# rule in one place and the write in another. The gate now lives INSIDE the write fence, on the
# rows the transaction actually reads; checked anywhere else it would be a race (the doctrine
# `_assert_legal_transition` records). Semantics mirror the tool path exactly: OPEN blocks;
# CLOSED passes; ABORTED does NOT block — a deliberation that can no longer conclude must not hold
# the task forever (U416), and the tool path reports it separately rather than blocking on it.

def test_record_synthesis_is_refused_while_a_debate_on_the_task_is_open(
        service: CollaborationService) -> None:
    """W-59 NEGATIVE (U410's P2 shape, aimed at the service rather than the tool path). Pre-repair
    this call returned a task with status COMPLETED while the debate was still OPEN."""
    cond, gemini, grok, task = assigned(service)
    tid = task["task_id"]
    service.open_debate(
        cond, task_id=tid, proposition="which risk ranks first",
        participant_node_ids=[gemini.node_id, grok.node_id], max_rounds=2,
    )
    service.record_candidate(gemini, task_id=tid,
                             candidate=_candidate(gemini.node_id, "sha256:gemini"))
    service.record_candidate(grok, task_id=tid,
                             candidate=_candidate(grok.node_id, "sha256:grok"))
    with pytest.raises(CollaborationError, match="still open"):
        service.record_synthesis(
            cond, task_id=tid, synthesis={"status": "SYNTHESIS", "artifact_ref": "sha256:s"},
            contribution_bindings=[
                {"node_id": gemini.node_id, "candidate_content_hash": "sha256:gemini"},
                {"node_id": grok.node_id, "candidate_content_hash": "sha256:grok"},
            ])
    after = service.get_task(cond, tid)
    assert after["status"] == "CANDIDATE_READY", "a refused synthesis must not advance the task"


def test_a_closed_debate_does_not_block_synthesis_at_the_service(
        service: CollaborationService) -> None:
    """W-59 POSITIVE, declared bound. The gate is OPEN-only, exactly like the tool path: a
    concluded debate is what a synthesis is built FROM, not a reason to refuse it."""
    cond, gemini, grok, task = assigned(service)
    tid = task["task_id"]
    debate = service.open_debate(
        cond, task_id=tid, proposition="which risk ranks first",
        participant_node_ids=[gemini.node_id, grok.node_id], max_rounds=1,
    )
    service.post_debate_turn(gemini, debate_id=debate["debate_id"], body="readiness first")
    service.post_debate_turn(grok, debate_id=debate["debate_id"], body="persistence first")
    service.close_debate(cond, debate_id=debate["debate_id"], decision="readiness first")
    service.record_candidate(gemini, task_id=tid,
                             candidate=_candidate(gemini.node_id, "sha256:gemini"))
    service.record_candidate(grok, task_id=tid,
                             candidate=_candidate(grok.node_id, "sha256:grok"))
    completed = service.record_synthesis(
        cond, task_id=tid, synthesis={"status": "SYNTHESIS", "artifact_ref": "sha256:s"},
        contribution_bindings=[
            {"node_id": gemini.node_id, "candidate_content_hash": "sha256:gemini"},
            {"node_id": grok.node_id, "candidate_content_hash": "sha256:grok"},
        ])
    assert completed["status"] == "COMPLETED"


def test_an_aborted_debate_does_not_block_synthesis_at_the_service(
        service: CollaborationService) -> None:
    """W-59 POSITIVE, declared bound. ABORTED is terminal-but-unconcluded (U416); it must not hold
    the task forever. Mirrors the tool path, which reports aborted debates separately instead of
    blocking on them."""
    cond, gemini, grok, task = assigned(service)
    tid = task["task_id"]
    debate = service.open_debate(
        cond, task_id=tid, proposition="which risk ranks first",
        participant_node_ids=[gemini.node_id, grok.node_id], max_rounds=2,
    )
    service.abort_debate(cond, debate_id=debate["debate_id"],
                         reason="a participant pane died before it could answer")
    service.record_candidate(gemini, task_id=tid,
                             candidate=_candidate(gemini.node_id, "sha256:gemini"))
    service.record_candidate(grok, task_id=tid,
                             candidate=_candidate(grok.node_id, "sha256:grok"))
    completed = service.record_synthesis(
        cond, task_id=tid, synthesis={"status": "SYNTHESIS", "artifact_ref": "sha256:s"},
        contribution_bindings=[
            {"node_id": gemini.node_id, "candidate_content_hash": "sha256:gemini"},
            {"node_id": grok.node_id, "candidate_content_hash": "sha256:grok"},
        ])
    assert completed["status"] == "COMPLETED"
