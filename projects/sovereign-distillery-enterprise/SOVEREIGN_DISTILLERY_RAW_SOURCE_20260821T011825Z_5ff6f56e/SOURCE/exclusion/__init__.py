from __future__ import annotations

from collections import defaultdict, deque

from distillery.common import ContractError, sha256_value


def exclude(source_id: str, nodes: list[dict], *, lineage_snapshot_hash: str) -> dict:
    if not source_id or not lineage_snapshot_hash:
        raise ContractError("source_id and immutable lineage snapshot hash are required")
    by_id = {node["sample_id"]: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ContractError("lineage contains duplicate sample IDs")
    children: dict[str, set[str]] = defaultdict(set)
    for node in nodes:
        for parent in node.get("derived_from", []):
            if parent not in by_id:
                raise ContractError(f"dangling lineage edge: {node['sample_id']} -> {parent}")
            children[parent].add(node["sample_id"])
    roots = {node["sample_id"] for node in nodes if node["sample_id"] == source_id or source_id in node.get("source_ids", [])}
    queue = deque(sorted(roots))
    excluded = set(roots)
    while queue:
        for child in sorted(children[queue.popleft()]):
            if child not in excluded:
                excluded.add(child)
                queue.append(child)
    remaining = [node for node in nodes if node["sample_id"] not in excluded]
    if any(excluded.intersection(node.get("derived_from", [])) for node in remaining):
        raise ContractError("rebuild manifest would contain residual excluded ancestry")
    body = {
        "lineage_snapshot_hash": lineage_snapshot_hash,
        "excluded_source": source_id,
        "excluded_sample_ids": sorted(excluded),
        "remaining_sample_ids": sorted(node["sample_id"] for node in remaining),
        "remaining_shard_hashes": sorted({node["shard_hash"] for node in remaining}),
    }
    return {**body, "manifest_hash": sha256_value(body)}


def e7_acceptance() -> dict:
    nodes = [
        {"sample_id": "x-root", "source_ids": ["TEST_CLIENT_X"], "derived_from": [], "shard_hash": "sx1"},
        {"sample_id": "x-child", "source_ids": [], "derived_from": ["x-root"], "shard_hash": "sx2"},
        {"sample_id": "x-grandchild", "source_ids": [], "derived_from": ["x-child"], "shard_hash": "sx3"},
        {"sample_id": "y-root", "source_ids": ["TEST_CLIENT_Y"], "derived_from": [], "shard_hash": "sy1"},
        {"sample_id": "y-child", "source_ids": [], "derived_from": ["y-root"], "shard_hash": "sy2"},
    ]
    first = exclude("TEST_CLIENT_X", nodes, lineage_snapshot_hash=sha256_value(nodes))
    second = exclude("TEST_CLIENT_X", nodes, lineage_snapshot_hash=sha256_value(nodes))
    assertions = {
        "x_direct_removed": "x-root" in first["excluded_sample_ids"],
        "x_descendants_removed": {"x-child", "x-grandchild"}.issubset(first["excluded_sample_ids"]),
        "excluded_hashes_absent": not {"sx1", "sx2", "sx3"}.intersection(first["remaining_shard_hashes"]),
        "y_retained": {"y-root", "y-child"}.issubset(first["remaining_sample_ids"]),
        "idempotent": first == second,
    }
    return {"passed": all(assertions.values()), "assertions": assertions, "manifest": first}
