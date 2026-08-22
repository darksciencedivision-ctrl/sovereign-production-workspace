"""Control-text leak guard.

Removes prompt-control labels (and their live values) that a model has
echoed back into its public speech. Operates on buffered, line-complete
text only -- a label split across two raw stream fragments must not slip
past detection just because it arrived in two pieces.

The blocked label set is not hand-maintained here: the caller passes in
the literal labels used by the prompt builder (see app.py's
TURN_PROMPT_LABELS), so the guard and the prompt can never drift apart.
"""

from __future__ import annotations

import re


def _strip_emphasis(line: str) -> str:
    """Remove a leading/trailing markdown bold marker before comparison."""
    stripped = line.strip()
    if stripped.startswith("**"):
        stripped = stripped[2:]
        if stripped.endswith("**"):
            stripped = stripped[:-2]
        stripped = stripped.strip()
    return stripped


class OutputGuard:
    """Detects and removes leaked control lines from buffered public text."""

    def __init__(self, labels, dynamic_values=None):
        self.labels = tuple(labels)
        self.dynamic_values = tuple(
            value.strip().lower()
            for value in (dynamic_values or [])
            if value and value.strip()
        )

    def _matched_label(self, candidate: str) -> str | None:
        for label in self.labels:
            if re.match(rf"^{re.escape(label)}", candidate, re.I):
                return label
        return None

    def _matched_dynamic(self, candidate_lower: str) -> bool:
        return any(
            candidate_lower.startswith(value) for value in self.dynamic_values
        )

    def scan_line(self, line: str) -> str | None:
        """Return the matched label (or a marker for a dynamic-value echo)
        if `line` is leaked control text, else None."""
        candidate = _strip_emphasis(line)
        if not candidate:
            return None
        label = self._matched_label(candidate)
        if label:
            return label
        if self._matched_dynamic(candidate.lower()):
            return "<dynamic control text>"
        return None

    def could_start_with_label(self, partial_line: str) -> bool:
        """True if `partial_line` (the start of a not-yet-terminated line)
        could still grow into a blocked line once more characters arrive.

        Used to release ordinary speech before a newline shows up -- most
        turns never contain one, so gating every emission on '\\n' would
        silently defeat live streaming. As soon as the buffered prefix
        diverges from every label and dynamic value, it is safe to release;
        a genuine leak never diverges, so it stays buffered until the line
        is complete and the full guard check in `filter_lines` runs.
        """
        candidate = partial_line.lstrip()
        if not candidate or candidate == "*":
            return True
        body = candidate[2:] if candidate.startswith("**") else candidate
        lowered = body.lower()
        if not lowered:
            return True
        for label in self.labels:
            label_lower = label.lower()
            if label_lower.startswith(lowered) or lowered.startswith(label_lower):
                return True
        for value in self.dynamic_values:
            if value.startswith(lowered) or lowered.startswith(value):
                return True
        return False

    def filter_lines(self, text: str) -> tuple[str, list[str]]:
        """Remove leaked control lines from buffered `text`.

        Returns (surviving_text, matched_labels). Surviving lines are
        rejoined with '\\n' in their original order; blocked lines are
        dropped entirely, and all valid speech before/after is preserved.
        """
        lines = text.split("\n")
        survivors = []
        matched = []
        for line in lines:
            hit = self.scan_line(line)
            if hit:
                matched.append(hit)
                continue
            survivors.append(line)
        return "\n".join(survivors), matched
