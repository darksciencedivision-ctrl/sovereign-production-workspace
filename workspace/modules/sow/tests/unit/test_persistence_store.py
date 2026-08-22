"""Phase 3A: store data-integrity — immutable append, provenance enforcement, CAS fencing,
content-addressed artifacts. No server, no policy."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from persistence import ContentAddressedStore, SovereignStore, StoreError


def _entry(entry_id="m-a", version=1, status="CANDIDATE", author="n1", prev=None) -> dict:
    return {
        "entry_id": entry_id, "project_id": "proj", "tier": "shared_project", "kind": "finding",
        "status": status, "content_hash": "sha256:" + "0" * 64, "version": version, "prev_version_ref": prev,
        "schema": "memory@1.0",
        "provenance": {"author_node": author, "task_id": None, "ts": datetime.now(timezone.utc).isoformat(),
                       "directive_version": "v2.4", "confidence": "medium"},
    }


@pytest.fixture()
def store(tmp_path: Path) -> SovereignStore:
    return SovereignStore(tmp_path / "s.db")


def test_append_and_read_back(store: SovereignStore) -> None:
    ref = store.append_memory_version(_entry())
    assert ref == "m-a@1"
    assert store.get_entry(ref)["status"] == "CANDIDATE"


def test_versions_are_immutable(store: SovereignStore) -> None:
    store.append_memory_version(_entry())
    with pytest.raises(StoreError, match="immutable"):
        store.append_memory_version(_entry())  # same entry_id@version


def test_provenance_required(store: SovereignStore) -> None:
    bad = _entry()
    del bad["provenance"]["confidence"]  # violates memory@1.0
    with pytest.raises(StoreError, match="memory@1.0"):
        store.append_memory_version(bad)


def test_cas_first_advance_and_conflict(store: SovereignStore) -> None:
    store.append_memory_version(_entry(version=1))
    r1 = store.cas_advance_head("m-a", "", "m-a@1", conflict_id="c-1")
    assert r1.ok and store.get_head("m-a") == "m-a@1"
    # a writer with a stale expected head loses and gets a conflict record
    store.append_memory_version(_entry(version=2, status="UNDER_REVIEW", prev="m-a@1"))
    r2 = store.cas_advance_head("m-a", "", "m-a@2", conflict_id="c-2", project_id="proj")  # expected genesis, head is @1
    assert not r2.ok
    assert r2.conflict["key"] == "m-a"
    assert len(r2.conflict["versions"]) >= 2
    assert store.get_head("m-a") == "m-a@1"  # unchanged — no silent overwrite
    assert len(store.list_conflicts("proj", "m-a")) == 1


def test_cas_correct_expected_advances(store: SovereignStore) -> None:
    store.append_memory_version(_entry(version=1))
    store.cas_advance_head("m-a", "", "m-a@1", conflict_id="c-1")
    store.append_memory_version(_entry(version=2, status="UNDER_REVIEW", prev="m-a@1"))
    r = store.cas_advance_head("m-a", "m-a@1", "m-a@2", conflict_id="c-2")
    assert r.ok and store.get_head("m-a") == "m-a@2"


def test_verify_detects_healthy_store(store: SovereignStore) -> None:
    store.append_memory_version(_entry(version=1))
    store.cas_advance_head("m-a", "", "m-a@1", conflict_id="c-1")
    assert store.verify()["ok"]


def test_cas_store_roundtrip_and_idempotent(tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas")
    ref = cas.put(b"hello world")
    assert ref == cas.put(b"hello world")  # idempotent
    assert cas.get(ref) == b"hello world"
    assert cas.exists(ref)


def test_cas_detects_tamper(tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas")
    ref = cas.put(b"content")
    path = cas._path_for(ref)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="mismatch"):
        cas.get(ref)


@pytest.mark.parametrize("evil", [
    "sha256:" + "../../../../etc/passwd".ljust(64, "a")[:64],   # traversal, 71 chars
    "sha256:" + "/" * 64,                                        # absolute-ish
    "sha256:" + "AA" + "0" * 62,                                 # uppercase (non-hex)
    "sha256:" + "0" * 63,                                        # too short
    "not-a-ref",
])
def test_cas_ref_traversal_and_shape_refused(tmp_path: Path, evil: str) -> None:
    """F3 pinned directly at the CAS boundary: a crafted ref never resolves a path (reverting
    the hex regex to a length check would fail this)."""
    cas = ContentAddressedStore(tmp_path / "cas")
    with pytest.raises(ValueError, match="not a valid artifact ref"):
        cas._path_for(evil)
