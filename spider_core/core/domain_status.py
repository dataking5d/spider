"""
Shared domain status writer — manages pipeline_status.json for all domains.

Usage:
    from core.domain_status import write_domain_status, init_domain

    # At pipeline start:
    init_domain("ai", "AI 前沿情报", status_path)

    # During pipeline:
    write_domain_status("ai", status_path, phase="fetching",
                        sources=[...], total_items=22, failed_count=0)

The module uses read-modify-write with retry to avoid clobbering other
domains' data when two pipelines write concurrently.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _read_status(path: Path) -> dict[str, Any]:
    """Read existing pipeline_status.json, return empty dict if missing/corrupt."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_status(path: Path, data: dict[str, Any]) -> None:
    """Atomic write with temp file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def init_domain(domain: str, label: str, status_path: Path,
                sub_domains: list[str] | None = None) -> None:
    """Register a domain in pipeline_status.json at pipeline start.

    Only sets label and initial state — does NOT overwrite an already-running
    domain's progress data. Subsequent write_domain_status() calls fill in
    the live data.
    """
    for _ in range(5):
        try:
            data = _read_status(status_path)
            data.setdefault("domains", {})

            old = data["domains"].get(domain, {})
            entry = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "label": label,
                "phase": "starting",
                "progress": old.get("progress", {"done": 0, "total": 0}),
                "sources": old.get("sources", []),
                "total_items": old.get("total_items", 0),
                "failed_count": old.get("failed_count", 0),
                "time": datetime.now().strftime("%H:%M:%S"),
            }
            if sub_domains:
                entry["sub_domains"] = sub_domains

            data["domains"][domain] = entry
            data["updated"] = datetime.now().strftime("%H:%M:%S")
            _write_status(status_path, data)
            return
        except Exception:
            time.sleep(0.05)
    # Last attempt — let it raise if it fails
    data = _read_status(status_path)
    data.setdefault("domains", {})
    data["domains"][domain] = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "label": label,
        "phase": "starting",
        "progress": {"done": 0, "total": 0},
        "sources": [],
        "total_items": 0,
        "failed_count": 0,
        "time": datetime.now().strftime("%H:%M:%S"),
    }
    if sub_domains:
        data["domains"][domain]["sub_domains"] = sub_domains
    data["updated"] = datetime.now().strftime("%H:%M:%S")
    _write_status(status_path, data)


def write_domain_status(domain: str, status_path: Path, *,
                        phase: str | None = None,
                        progress: dict[str, int] | None = None,
                        sources: list[dict[str, Any]] | None = None,
                        total_items: int | None = None,
                        failed_count: int | None = None,
                        sub_domains: list[str] | None = None,
                        label: str | None = None,
                        extra: dict[str, Any] | None = None) -> None:
    """Write domain-specific status to pipeline_status.json.

    Only updates the fields you pass — other domains' data is left untouched.
    Retries on file conflict (another domain writing simultaneously).
    """
    now = datetime.now().strftime("%H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    for _ in range(5):
        try:
            data = _read_status(status_path)
            data.setdefault("domains", {})

            domain_data = data["domains"].get(domain, {})
            domain_data["time"] = now
            domain_data["date"] = today
            if phase is not None:
                domain_data["phase"] = phase
            if progress is not None:
                domain_data["progress"] = progress
            if sources is not None:
                domain_data["sources"] = sources
            if total_items is not None:
                domain_data["total_items"] = total_items
            if failed_count is not None:
                domain_data["failed_count"] = failed_count
            if sub_domains is not None:
                domain_data["sub_domains"] = sub_domains
            if label is not None:
                domain_data["label"] = label
            if extra is not None:
                # `extra` is merged FLAT into domain_data, so a clear must remove
                # the keys it contributed by name. The previous implementation
                # popped "extra", a key that never exists — so the documented
                # "explicitly empty extra clears stale data" was a silent no-op,
                # and a fresh run's status sat beside the previous run's scores.
                for stale_key in domain_data.pop("_extra_keys", []):
                    domain_data.pop(stale_key, None)
                if extra:
                    domain_data.update(extra)
                    domain_data["_extra_keys"] = list(extra.keys())

            data["domains"][domain] = domain_data
            data["updated"] = now
            _write_status(status_path, data)
            return
        except Exception:
            time.sleep(0.05)
    # Last attempt — let it raise
    data = _read_status(status_path)
    data.setdefault("domains", {})
    domain_data = data["domains"].get(domain, {})
    domain_data["time"] = now
    domain_data["date"] = today
    if phase is not None:
        domain_data["phase"] = phase
    if progress is not None:
        domain_data["progress"] = progress
    if sources is not None:
        domain_data["sources"] = sources
    if total_items is not None:
        domain_data["total_items"] = total_items
    if failed_count is not None:
        domain_data["failed_count"] = failed_count
    if sub_domains is not None:
        domain_data["sub_domains"] = sub_domains
    if label is not None:
        domain_data["label"] = label
    if extra is not None:
        # Same flat-merge semantics as the retry path above — see the comment there.
        for stale_key in domain_data.pop("_extra_keys", []):
            domain_data.pop(stale_key, None)
        if extra:
            domain_data.update(extra)
            domain_data["_extra_keys"] = list(extra.keys())
    data["domains"][domain] = domain_data
    data["updated"] = now
    _write_status(status_path, data)
