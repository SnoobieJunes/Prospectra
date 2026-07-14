# 2026-07-13 (P3): Findings persistence — a scan's results land in the project file with their
# lineage (dataset + sample seed), so they survive restarts, can be reproduced exactly, and can be
# handed to the P4 hypothesis engine ("why might this be?") without re-running the scan.

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from prospectra.core.mining.scan import ScanResult
from prospectra.core.project import ProjectStore


def save_scan(store: ProjectStore, scan: ScanResult, flow_id: str | None = None) -> int:
    """Write every significant finding into the project's findings table. Returns the count."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    rows = [
        (
            uuid.uuid4().hex,
            finding.kind,
            finding.title,
            json.dumps(
                {
                    "headline": finding.headline,
                    "columns": finding.columns,
                    "effect": finding.effect,
                    "effect_name": finding.effect_name,
                    "p_value": finding.p_value,
                    "q_value": finding.q_value,
                    "n": finding.n,
                    "payload": finding.payload,
                    "target": scan.target,
                }
            ),
            flow_id,
            scan.dataset,
            scan.seed,
            now,
        )
        for finding in scan.findings
    ]
    store._conn.executemany(
        "INSERT INTO findings(id, kind, title, payload_json, flow_id, dataset_ref, sample_seed, "
        "created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    store._conn.commit()
    return len(rows)
