"""
Shared logger engine — domain-aware routing with backward-compatible single-domain API.

Usage:
    from core.logger import log_event
    log_event("ai", "something happened")

    # Backward-compatible:
    from core.logger import log
    log("something happened")
"""
from datetime import datetime
from pathlib import Path


def log(msg: str, log_dir: Path | None = None) -> None:
    """Append a [HH:MM:SS] message to today's log file.

    If log_dir is not provided, defaults to <cwd>/logs/.
    """
    try:
        if log_dir is None:
            log_dir = Path.cwd() / "logs"
        log_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%H:%M:%S")
        log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
        print(f"[LOG {ts}] {msg}")
    except Exception:
        pass  # Log failure must never crash the pipeline


def log_event(domain: str, msg: str, base_dir: Path | None = None) -> None:
    """Append a [HH:MM:SS] message to {base_dir}/{domain}/YYYY-MM-DD.log.

    Domain-aware routing: each domain gets its own subdirectory.
    If base_dir is not provided, defaults to <cwd>/logs/.
    """
    try:
        if base_dir is None:
            base_dir = Path.cwd() / "logs"
        log_dir = base_dir / domain
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%H:%M:%S")
        log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
        print(f"[{domain.upper()} {ts}] {msg}")
    except Exception:
        pass  # Log failure must never crash the pipeline
