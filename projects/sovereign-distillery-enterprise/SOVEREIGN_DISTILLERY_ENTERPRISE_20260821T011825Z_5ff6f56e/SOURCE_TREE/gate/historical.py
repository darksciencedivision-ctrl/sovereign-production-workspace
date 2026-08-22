from __future__ import annotations

import json
from pathlib import Path

from distillery.common import ContractError, utc_now


REQUIRED = {"suite_version", "bundle_id", "n", "mean", "dispersion", "ci_metadata", "promotion_time"}


class HistoricalBestStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append_promotion_run(self, row: dict) -> None:
        missing = REQUIRED - row.keys()
        if missing or not row["promotion_time"] or row["n"] < 1:
            raise ContractError(f"invalid historical promotion row; missing={sorted(missing)}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({**row, "recorded_at": utc_now()}, sort_keys=True, allow_nan=False) + "\n")

    def records(self, suite_version: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [row for row in rows if suite_version is None or row["suite_version"] == suite_version]

    def reference(self, suite_version: str) -> dict:
        grouped: dict[str, list[dict]] = {}
        for row in self.records(suite_version):
            grouped.setdefault(row["bundle_id"], []).append(row)
        aggregates = []
        for bundle_id, rows in grouped.items():
            if len(rows) < 2:
                continue
            total_n = sum(row["n"] for row in rows)
            aggregates.append({"bundle_id": bundle_id, "mean": sum(row["mean"] * row["n"] for row in rows) / total_n, "n": total_n, "promotion_run_count": len(rows), "max_single_run_ignored": max(row["mean"] for row in rows)})
        if not aggregates:
            raise ContractError("historical best requires at least two promotion-time runs for a bundle")
        return max(aggregates, key=lambda item: (item["mean"], item["n"]))
