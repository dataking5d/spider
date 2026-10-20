"""
Spider Health — daily system health scoring (domain-agnostic).

Reads task_registry.json for expected domains, pipeline_status.json for
current run data, and iterates dynamically over all domains. No hardcoded
domain names, directory paths, or domain counts.

Output: writes to pipeline_status.json -> "health" field,
         displayed on dashboard as a health KPI row.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _get_expected_domains(project_root: Path) -> list[dict[str, Any]]:
    """Read task_registry.json for the authoritative list of enabled domains."""
    registry = _load_json(project_root / "task_registry.json")
    if not registry:
        return []
    return [t for t in registry.get("tasks", []) if t.get("enabled", True)]


def compute_health(project_root: Path, today: str | None = None) -> dict[str, Any]:
    """Compute today's Spider health score — fully domain-agnostic."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    status_path = project_root / "pipeline_status.json"
    memory_dir = project_root / "memory"

    expected = _get_expected_domains(project_root)
    expected_ids = {t["id"] for t in expected}
    expected_count = len(expected)

    score = 100
    checks: list[dict[str, Any]] = []
    details: dict[str, Any] = {}

    # ── 1. Domain completion ──────────────────────────
    status = _load_json(status_path) or {}
    domains_data = status.get("domains", {})
    domains_ok = 0
    domains_stale = 0

    for domain_id in expected_ids:
        d = domains_data.get(domain_id, {})
        domain_date = d.get("date", "")
        if domain_date == today and d.get("phase") == "done":
            domains_ok += 1
        elif domain_date != today:
            domains_stale += 1
            score -= 40
            label = d.get("label", domain_id)
            checks.append({
                "check": f"{domain_id}_complete", "status": "fail",
                "msg": f"{label} stale data ({domain_date or 'no date'}), not run today",
            })
        else:
            score -= 40
            label = d.get("label", domain_id)
            checks.append({
                "check": f"{domain_id}_complete", "status": "fail",
                "msg": f"{label} did not complete",
            })

    details["domains"] = f"{domains_ok}/{expected_count} OK"
    if domains_stale > 0:
        details["domains"] += f" ({domains_stale} stale)"
    if domains_ok == expected_count and expected_count > 0:
        checks.append({
            "check": "all_domains_complete", "status": "ok",
            "msg": f"All {expected_count} domains completed",
        })

    # ── 2. Source health (all domains, from pipeline_status) ──
    total_sources_ok = 0
    total_sources_fail = 0
    for domain_id in expected_ids:
        d = domains_data.get(domain_id, {})
        domain_date = d.get("date", "")
        if domain_date != today:
            continue
        sources = d.get("sources", [])
        if not sources:
            continue
        ok = sum(1 for s in sources if s.get("status") == "ok")
        fail = len(sources) - ok
        total_sources_ok += ok
        total_sources_fail += fail
        details[f"{domain_id}_sources"] = f"{ok}/{len(sources)} OK"

    total_sources = total_sources_ok + total_sources_fail
    if total_sources > 0:
        fail_rate = total_sources_fail / total_sources
        if fail_rate > 0.3:
            score -= 25
            checks.append({
                "check": "sources", "status": "fail",
                "msg": f"{total_sources_fail}/{total_sources} sources failed across all domains",
            })
        elif fail_rate > 0.1:
            score -= 10
            checks.append({
                "check": "sources", "status": "warn",
                "msg": f"{total_sources_fail}/{total_sources} sources failed",
            })
        else:
            checks.append({
                "check": "sources", "status": "ok",
                "msg": f"{total_sources_ok}/{total_sources} sources OK across {expected_count} domains",
            })

    # ── 3. Runtime (sum across all domain timing files) ──
    total_runtime_s = 0
    logs_dir = project_root / "logs"
    for domain_id in expected_ids:
        timing_path = logs_dir / domain_id / f"{today}-timing.jsonl"
        timing_data = _load_json(timing_path)
        if timing_data:
            total_runtime_s += timing_data.get("total_s", 0)

    details["total_runtime_s"] = int(total_runtime_s)
    if total_runtime_s > 1200:
        score -= 15
        checks.append({
            "check": "runtime", "status": "warn",
            "msg": f"Total runtime {total_runtime_s:.0f}s (> 20min)",
        })
    elif total_runtime_s > 0:
        checks.append({
            "check": "runtime", "status": "ok",
            "msg": f"Total runtime {total_runtime_s:.0f}s",
        })

    # ── 4. Dedup health (iterate memory/*/topic_fingerprints.json) ──
    fp_count = 0
    for domain_id in expected_ids:
        fp_path = memory_dir / domain_id / "topic_fingerprints.json"
        fp_data = _load_json(fp_path)
        if fp_data:
            fp_count += len(fp_data)

    details["topic_fingerprints"] = fp_count
    if fp_count > 0:
        checks.append({
            "check": "dedup", "status": "ok",
            "msg": f"{fp_count} topic fingerprints across {expected_count} domains",
        })
    else:
        checks.append({
            "check": "dedup", "status": "warn",
            "msg": "No topic fingerprints yet (first run?)",
        })

    # ── 5. Claude call status (from pipeline_status.json) ──
    claude_failures = 0
    degraded_domains = []
    for domain_id in expected_ids:
        d = domains_data.get(domain_id, {})
        domain_date = d.get("date", "")
        if domain_date != today:
            continue
        reason = None

        # `extra` is merged FLAT into the domain dict by write_domain_status(),
        # so there is no nested d["extra"] to read — checking it was a silent
        # no-op that let every degraded run score A/100 (see 2026-09-29).
        if d.get("degraded"):
            reason = d.get("error_hint") or "产出为占位文件，非真实内容"
        elif d.get("error"):
            reason = str(d["error"])[:80]

        if reason:
            claude_failures += 1
            degraded_domains.append(f"{d.get('label', domain_id)}（{reason}）")
        elif d.get("phase") != "done":
            claude_failures += 1

    if claude_failures == 0:
        checks.append({"check": "claude", "status": "ok", "msg": "Claude calls OK"})
    else:
        score -= 40 * claude_failures
        msg = f"{claude_failures} 个 domain 未产出真实内容"
        if degraded_domains:
            msg += "：" + "；".join(degraded_domains)
        checks.append({"check": "claude", "status": "fail", "msg": msg})

    # ── 6. Memory state (iterate memory/*/trends.json) ──
    mem_days = 0
    for domain_id in expected_ids:
        trends = _load_json(memory_dir / domain_id / "trends.json")
        if trends:
            mem_days = max(mem_days, trends.get("total_days", 0))

    details["memory_days"] = mem_days
    if mem_days > 0:
        checks.append({
            "check": "memory", "status": "ok",
            "msg": f"{mem_days} days of trend memory across {expected_count} domains",
        })
    else:
        checks.append({
            "check": "memory", "status": "warn",
            "msg": "No trend memory yet",
        })

    # ── Grade ──────────────────────────────────────────
    score = max(0, min(100, score))
    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    return {
        "date": today,
        "grade": grade,
        "score": score,
        "details": details,
        "checks": checks,
    }


def write_health(project_root: Path, today: str | None = None) -> dict[str, Any]:
    """Compute health and write to pipeline_status.json."""
    health = compute_health(project_root, today)
    status_path = project_root / "pipeline_status.json"

    data = _load_json(status_path) or {}
    data["health"] = health
    data["health"]["updated"] = datetime.now().strftime("%H:%M:%S")
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    tmp = status_path.with_suffix(".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(status_path)
    except OSError as first_err:
        last_err = first_err
        for attempt in range(3):
            try:
                status_path.write_text(payload, encoding="utf-8")
                last_err = None
                break
            except Exception as e:
                last_err = e
                time.sleep(0.5)
        if last_err is not None:
            # Every attempt failed (typically a lock held by the dashboard
            # polling pipeline_status.json). Raise so the caller sees it —
            # previously this slipped through silently and the health block
            # just went stale with no trace.
            raise OSError(
                f"write_health: could not persist to {status_path}: {last_err}"
            ) from last_err

    return health
