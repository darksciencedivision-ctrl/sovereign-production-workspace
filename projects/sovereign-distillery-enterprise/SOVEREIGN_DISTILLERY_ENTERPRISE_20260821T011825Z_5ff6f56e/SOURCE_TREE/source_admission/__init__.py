from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Iterable

from distillery.common import ContractError, sha256_value, utc_now


class AdmissionClass(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


ALLOWED_TRANSITIONS = {
    AdmissionClass.UNKNOWN: {AdmissionClass.ELIGIBLE, AdmissionClass.INTERNAL_ONLY, AdmissionClass.REJECTED},
    AdmissionClass.INTERNAL_ONLY: {AdmissionClass.ELIGIBLE, AdmissionClass.REJECTED},
    AdmissionClass.ELIGIBLE: {AdmissionClass.INTERNAL_ONLY, AdmissionClass.REJECTED},
    AdmissionClass.REJECTED: set(),
}


@dataclass(frozen=True, order=True)
class SourceKey:
    provider: str
    teacher_or_model_id: str
    revision: str

    def __post_init__(self) -> None:
        if not all((self.provider, self.teacher_or_model_id, self.revision)):
            raise ContractError("source identity fields must be non-empty")


@dataclass(frozen=True)
class AdmissionEvent:
    provider: str
    teacher_or_model_id: str
    revision: str
    previous_class: str
    new_class: str
    use_class: str
    evidence_or_terms_ref: str
    decision_ts: str
    decision_authority: str
    notes: str = ""


class AdmissionRegistry:
    def __init__(self, events: Iterable[AdmissionEvent] = ()) -> None:
        self._events: list[AdmissionEvent] = []
        for event in events:
            self._append_existing(event)

    @property
    def events(self) -> tuple[AdmissionEvent, ...]:
        return tuple(self._events)

    def current(self, key: SourceKey) -> AdmissionClass:
        for event in reversed(self._events):
            if (event.provider, event.teacher_or_model_id, event.revision) == (key.provider, key.teacher_or_model_id, key.revision):
                return AdmissionClass(event.new_class)
        return AdmissionClass.UNKNOWN

    def transition(self, key: SourceKey, new_class: AdmissionClass, *, evidence_ref: str, decision_authority: str, effective_time: str | None = None, notes: str = "") -> AdmissionEvent:
        previous = self.current(key)
        if new_class not in ALLOWED_TRANSITIONS[previous]:
            raise ContractError(f"forbidden admission transition: {previous} -> {new_class}")
        if not evidence_ref or not decision_authority:
            raise ContractError("admission changes require evidence and decision authority")
        event = AdmissionEvent(key.provider, key.teacher_or_model_id, key.revision, previous.value, new_class.value, new_class.value, evidence_ref, effective_time or utc_now(), decision_authority, notes)
        self._events.append(event)
        return event

    def _append_existing(self, event: AdmissionEvent) -> None:
        key = SourceKey(event.provider, event.teacher_or_model_id, event.revision)
        previous = self.current(key)
        if previous.value != event.previous_class or AdmissionClass(event.new_class) not in ALLOWED_TRANSITIONS[previous]:
            raise ContractError("invalid historical admission event chain")
        self._events.append(event)

    def snapshot(self, run_id: str) -> dict:
        if not run_id:
            raise ContractError("run_id is required")
        keys = sorted({SourceKey(e.provider, e.teacher_or_model_id, e.revision) for e in self._events})
        sources = [{"provider": key.provider, "teacher_or_model_id": key.teacher_or_model_id, "revision": key.revision, "use_class": self.current(key).value} for key in keys]
        body = {"run_id": run_id, "sources": sources, "events": [asdict(event) for event in self._events]}
        return {**body, "snapshot_hash": sha256_value(body)}


def assert_admitted(use_class: str, *, internal_use_authorized: bool = False) -> None:
    try:
        classification = AdmissionClass(use_class)
    except ValueError as exc:
        raise ContractError(f"unknown source admission class: {use_class!r}") from exc
    if classification in {AdmissionClass.UNKNOWN, AdmissionClass.REJECTED}:
        raise ContractError(f"source class {classification} is not admitted")
    if classification is AdmissionClass.INTERNAL_ONLY and not internal_use_authorized:
        raise ContractError("INTERNAL_ONLY requires an authorized internal-use lineage")


def assert_seed_admitted(use_class: str, *, internal_use_authorized: bool = False) -> None:
    assert_admitted(use_class, internal_use_authorized=internal_use_authorized)
