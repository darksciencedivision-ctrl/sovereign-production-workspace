"""The Phase 19 pytest wrapper's TERMINATION path (punch list 6.12).

The wrapper exists to hold the committed wall-clock ceiling. It could not: on a
timeout it sent SIGTERM to the process group and then called `process.wait()`
with **no timeout**, so a child that ignores termination hung the wrapper
forever and the ceiling never fired. On Windows `_terminate_tree` already used
`taskkill /T /F`, which cannot be ignored; the unbounded wait was a defect on
both platforms and the soft-only signal was a defect on POSIX.

These tests never spawn a real unkillable child. The policy is isolated and
falsified deterministically: the stub's `wait()` raises on the UNBOUNDED call,
so the defect shows up as an explicit failure instead of hanging the suite that
is testing it.
"""
from __future__ import annotations

import subprocess

import pytest

from tools import run_phase19_pytest as mod


class _IgnoresTermination:
    """A child that survives the soft signal and dies only on the hard kill."""

    def __init__(self, *, dies_on_hard_kill: bool = True) -> None:
        self.hard_killed = False
        self.dies_on_hard_kill = dies_on_hard_kill
        self.pid = 4242
        self.bounded_waits: list[float] = []

    def poll(self):
        return -9 if (self.hard_killed and self.dies_on_hard_kill) else None

    def wait(self, timeout=None):
        if timeout is None:
            raise AssertionError(
                "the runner waited on a terminated child with NO timeout: a child that ignores "
                "termination hangs here forever and the committed ceiling never fires")
        self.bounded_waits.append(timeout)
        if self.hard_killed and self.dies_on_hard_kill:
            return -9
        raise subprocess.TimeoutExpired("pytest", timeout)


def _install(monkeypatch, child):
    """Bind the stub in place of a real spawn, and record the escalation steps."""
    steps: list[bool] = []

    def _fake_terminate(process, hard=False):
        steps.append(bool(hard))
        if hard:
            process.hard_killed = True

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(mod, "_terminate_tree", _fake_terminate)
    return steps


def test_a_child_that_ignores_termination_is_hard_killed_within_a_declared_ceiling(
        monkeypatch, capsys) -> None:
    """6.12 NEGATIVE. Pre-repair this fails on the unbounded `wait()` assertion above."""
    child = _IgnoresTermination()
    steps = _install(monkeypatch, child)

    rc = mod.main(["full"])

    assert steps == [False, True], (
        f"expected terminate then hard-kill escalation, got {steps}")
    assert rc == 124, "a suite that blew its ceiling still reports the ceiling code"
    assert all(t is not None and t > 0 for t in child.bounded_waits), (
        "every wait after the ceiling must be BOUNDED")
    assert "ceiling" in capsys.readouterr().err


def test_a_child_that_survives_the_hard_kill_is_an_explicit_failure(
        monkeypatch, capsys) -> None:
    """6.12 NEGATIVE, the other end: unreaped must be REPORTED, never waited on forever."""
    child = _IgnoresTermination(dies_on_hard_kill=False)
    steps = _install(monkeypatch, child)

    rc = mod.main(["full"])

    assert steps == [False, True]
    assert rc != 0 and rc != 124, (
        "a tree that outlived the hard kill is a different outcome from a plain ceiling breach")
    err = capsys.readouterr().err
    assert "ceiling" in err
    assert "unreaped" in err.lower() or "did not" in err.lower()


def test_a_suite_that_finishes_inside_the_ceiling_is_untouched(monkeypatch) -> None:
    """POSITIVE. The escalation must not run for a normal completion."""
    class _Finishes:
        pid = 4242

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    steps = _install(monkeypatch, _Finishes())
    assert mod.main(["full"]) == 0
    assert steps == [], "no termination step may run when the suite finished on its own"


def test_the_escalation_bounds_are_declared_and_positive() -> None:
    """The ceiling is only a ceiling if every wait beneath it is finite."""
    assert isinstance(mod.TERMINATE_GRACE_SECONDS, (int, float))
    assert isinstance(mod.HARD_KILL_GRACE_SECONDS, (int, float))
    assert mod.TERMINATE_GRACE_SECONDS > 0
    assert mod.HARD_KILL_GRACE_SECONDS > 0


def test_the_posix_soft_signal_escalates_to_SIGKILL(monkeypatch) -> None:
    """POSIX-only half of the defect: the soft path sent SIGTERM and nothing else. Asserted
    through the signal the code selects, so it is checked on this Windows host too."""
    if mod.os.name == "nt":
        pytest.skip("POSIX process-group signalling; the Windows path uses taskkill /T /F")
    sent: list[int] = []
    monkeypatch.setattr(mod.os, "killpg", lambda pid, sig: sent.append(sig))
    proc = _IgnoresTermination()
    mod._terminate_tree(proc)                 # noqa: SLF001 - the unit under test
    mod._terminate_tree(proc, hard=True)      # noqa: SLF001
    assert sent == [mod.signal.SIGTERM, mod.signal.SIGKILL]
