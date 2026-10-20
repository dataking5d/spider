"""
Health / observability writer — domain-aware routing, structured JSON output.

Usage:
    from core.renderer import HealthWriter, write_health

    # One-shot:
    write_health("ai", source_status=[...], runtime_s=293, ...)

    # Class-based:
    hw = HealthWriter("cognition")
    hw.set_source_status("Papers with Code", "FAILED", "timeout")
    hw.set_pipeline("success", runtime_s=180, total_items=12)
    hw.write()

Output structure (mirrors logs/ and reports/):
    health/
    ├── ai/
    │   └── 2026-05-27-health.json
    └── cognition/
        └── 2026-05-27-health.json

Extensible fields (no schema migration needed):
    - retry_count, telemetry_latency (future)
    - orchestration_dag, trend_memory_snapshot (future)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HealthWriter:
    """Domain-aware health/observability writer.

    Routes to health/{domain}/YYYY-MM-DD-health.json.
    Mirrors: logs/{domain}/YYYY-MM-DD.log, reports/{domain}/YYYY-MM-DD-{type}.md.
    """

    def __init__(self, domain: str, base_dir: Path | None = None) -> None:
        self.domain = domain
        self._base = base_dir or Path.cwd() / "health"
        self._health_dir = self._base / domain
        self._health_dir.mkdir(parents=True, exist_ok=True)

        self._source_status: list[dict[str, Any]] = []
        self._pipeline: dict[str, Any] = {}
        self._dedup: dict[str, Any] = {}
        self._extra: dict[str, Any] = {}

    # -- source status -------------------------------------------------

    def set_source_status(self, name: str, status: str,
                          items: int = 0, error: str = "", **extra: Any) -> None:
        """Record a single source's fetch status."""
        entry: dict[str, Any] = {"name": name, "status": status}
        if status == "OK":
            entry["items"] = items
        if error:
            entry["error"] = error
        entry.update(extra)
        self._source_status.append(entry)

    def set_source_batch(self, sources: list[dict[str, Any]]) -> None:
        """Replace all source status entries at once."""
        self._source_status = list(sources)

    # -- pipeline ------------------------------------------------------

    def set_pipeline(self, status: str, **fields: Any) -> None:
        """Set pipeline-level summary fields.

        Common: runtime_s, total_items, failed_sources, ai_summary_ok, report_generated.
        Future: retry_count, telemetry_latency_ms, orchestration_dag.
        """
        self._pipeline = {"status": status, **fields}

    # -- dedup ---------------------------------------------------------

    def set_dedup(self, **fields: Any) -> None:
        """Set dedup pipeline stats.

        Common: redis_enabled, redis_available, redis_items_filtered,
                redis_fingerprints_before, redis_fingerprints_after,
                pipeline_dedup_removed.
        """
        self._dedup = fields

    # -- extensibility -------------------------------------------------

    def set_extra(self, **fields: Any) -> None:
        """Attach arbitrary data for future consumers.

        Use for: retry_count, telemetry, orchestration, trend_memory_snapshot.
        No schema — consumers are expected to handle missing keys gracefully.
        """
        self._extra.update(fields)

    # -- write ---------------------------------------------------------

    def write(self, date_str: str | None = None) -> Path:
        """Write health record as structured JSON with atomic write.

        Returns the output path.
        Health failure must never crash the pipeline — caller handles the exception.
        """
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        output_path = self._health_dir / f"{date_str}-health.json"

        record: dict[str, Any] = {
            "domain": self.domain,
            "date": date_str,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_status": self._source_status,
            "pipeline": self._pipeline,
        }
        if self._dedup:
            record["dedup"] = self._dedup
        if self._extra:
            record["extra"] = self._extra

        tmp_path = output_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            if output_path.exists():
                backup_path = output_path.with_suffix(".json.bak")
                output_path.replace(backup_path)

            tmp_path.replace(output_path)
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise

        return output_path

    # -- path helpers --------------------------------------------------

    def today_path(self) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self._health_dir / f"{date_str}-health.json"

    def latest_health(self) -> Path | None:
        candidates = sorted(self._health_dir.glob("*-health.json"), reverse=True)
        return candidates[0] if candidates else None


def write_health(domain: str, base_dir: Path | None = None,
                 source_status: list[dict[str, Any]] | None = None,
                 pipeline: dict[str, Any] | None = None,
                 extra: dict[str, Any] | None = None,
                 date_str: str | None = None) -> Path:
    """One-shot domain-aware health write.

    Routes to health/{domain}/YYYY-MM-DD-health.json.
    Returns the output path.
    """
    hw = HealthWriter(domain, base_dir=base_dir)
    if source_status:
        hw.set_source_batch(source_status)
    if pipeline:
        hw.set_pipeline(**pipeline)
    if extra:
        hw.set_extra(**extra)
    return hw.write(date_str=date_str)
