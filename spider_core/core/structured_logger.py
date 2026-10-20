"""
Structured logger for Spider — console + phase timing.

Usage:
    from core.structured_logger import SpiderLogger, PhaseTimer

    slog = SpiderLogger(domain="cognition")
    slog.info("fetch_complete", stage="fetch", source="reddit", score=8.2)

    timer = PhaseTimer("ai", base_dir=logs_dir, logger=slog)
    timer.start("fetch")
    # ... work ...
    timer.end("fetch")
    timer.write_summary()
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

_configured = False


def _ensure_configured():
    global _configured
    if _configured:
        return
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            # utc=False is load-bearing. TimeStamper defaults to utc=True, so the
            # console line and the `timestamp` field of the very same JSONL record
            # (`datetime.now()`, below) disagreed by the UTC offset — on this
            # machine 8h, printed one line apart in the same log directory.
            # Measured 2026-10-07: console 17:45:25 / jsonl 01:45:25 for one event.
            structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


class SpiderLogger:
    """Domain-aware structured logger (console + daily JSONL file).

    Console: structlog with ConsoleRenderer.
    File:   logs/<domain>/YYYY-MM-DD.jsonl — one JSON record per line.

    Fields are arbitrary kwargs — no schema enforcement.
    Common fields: stage, task, status, runtime, score, source.
    """

    def __init__(self, domain: str, base_dir: str | Path | None = None) -> None:
        _ensure_configured()
        self.domain = domain
        self._base = Path(base_dir) if base_dir else None

    def debug(self, event: str, **fields: Any) -> None:
        self._emit("debug", event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit("info", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit("warning", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit("error", event, **fields)

    def _emit(self, level: str, event: str, **fields: Any) -> None:
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        record = {"domain": self.domain, "event": event, "level": level,
                  "timestamp": ts}
        record.update(fields)

        # Console
        try:
            ctx = structlog.get_logger().bind(**record)
            getattr(ctx, level)(event)
        except Exception as e:
            print(f"[SpiderLogger console ERROR] {e}")

        # File — append JSONL to logs/<domain>/YYYY-MM-DD.jsonl
        if self._base:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                log_dir = self._base / self.domain
                log_dir.mkdir(parents=True, exist_ok=True)
                log_path = log_dir / f"{today}.jsonl"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[SpiderLogger file ERROR] {e}")

    def close(self) -> None:
        pass


class PhaseTimer:
    """Record phase-level timing and write structured JSONL log.

    Usage:
        timer = PhaseTimer("ai", base_dir=logs_dir, logger=slog)
        timer.start("fetch")
        # ...
        timer.end("fetch")
        timer.write_summary()  # prints timing table + writes .jsonl
    """

    def __init__(self, domain: str, base_dir: Path | None = None,
                 logger: SpiderLogger | None = None) -> None:
        self.domain = domain
        self._base = base_dir or Path.cwd()
        self._log = logger
        self._phases: list[dict[str, Any]] = []
        self._starts: dict[str, float] = {}
        self._pipeline_start = time.time()

    def start(self, phase: str) -> None:
        self._starts[phase] = time.time()
        if self._log:
            self._log.info("phase_start", stage=phase)

    def end(self, phase: str) -> None:
        t0 = self._starts.pop(phase, None)
        elapsed = round(time.time() - t0, 2) if t0 else 0.0
        self._phases.append({
            "phase": phase,
            "elapsed_s": elapsed,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        })
        if self._log:
            self._log.info("phase_end", stage=phase, elapsed_s=elapsed)

    def write_summary(self) -> Path | None:
        """Write timing summary to logs/<domain>/YYYY-MM-DD-timing.jsonl.

        Also prints a compact timing table to stdout.
        Returns the file path.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        total = round(time.time() - self._pipeline_start, 2)

        # ── JSONL output FIRST (before console — survives encoding errors) ──
        log_dir = self._base / self.domain
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{today}-timing.jsonl"

        record = {
            "date": today,
            "domain": self.domain,
            "total_s": total,
            "phases": self._phases,
        }
        try:
            path.write_text(json.dumps(record, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        except Exception as e:
            print(f"[PhaseTimer ERROR] Failed to write timing file: {e}")
            return None

        # ── Console summary (ASCII-only — safe on Windows GBK terminals) ──
        try:
            print(f"\n{'=' * 45}")
            print(f"  Phase Timing -- {self.domain.upper()} Domain")
            print(f"{'=' * 45}")
            for p in self._phases:
                bar = self._bar(p["elapsed_s"], total)
                print(f"  {p['phase']:<22s} {p['elapsed_s']:>7.1f}s  {bar}")
            print(f"  {'-' * 35}")
            print(f"  {'TOTAL':<22s} {total:>7.1f}s")
            print(f"{'=' * 45}")
            print(f"  Timing saved -> {path}")
        except UnicodeEncodeError:
            pass  # OK, file is already written

        return path

    @staticmethod
    def _bar(elapsed: float, total: float, width: int = 12) -> str:
        if total <= 0:
            return ""
        pct = min(elapsed / total, 1.0)
        filled = int(pct * width)
        return "#" * filled + "-" * (width - filled)

    @property
    def total_s(self) -> float:
        return round(time.time() - self._pipeline_start, 2)
