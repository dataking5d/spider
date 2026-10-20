"""
Shared output path resolver — handles duplicate filenames for manual re-runs.

Usage:
    from core.output_utils import resolve_output_path

    path = Path("reports/2026-06-11_AI情报.md")
    manual_path = resolve_output_path(path)  # → 2026-06-11_AI情报（1）.md
"""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path


def agent_draft_staging_dir(domain: str) -> Path:
    """Directory the child `claude` CLI is allowed to write a draft into.

    The CLI refuses to write anywhere under its own config directory
    (CLAUDE_CONFIG_DIR — here D:\\.claude), and 小蜘蛛 lives *inside* that tree,
    so the child cannot create anything under reports/<domain>/drafts/.
    Measured 2026-10-06 on CLI 2.1.291: a probe Write inside the project was
    denied under both `dontAsk` and `acceptEdits`, and `--add-dir <project>` did
    not help; the same probe in %TEMP% succeeded. Python is an ordinary process
    and is not restricted, so the child stages here and Python archives the
    result back into the project with archive_agent_draft().
    """
    return Path(tempfile.gettempdir()) / "spider_drafts" / domain


def archive_agent_draft(staging: Path, destination: Path) -> bool:
    """Move a child-written staging draft to its in-project drafts path.

    Drafts still land in the project (rejected ones stay there for diagnosis);
    only the child's write target moved. Returns False when the child wrote
    nothing — the caller reports a missing draft rather than crashing, because
    "the model returned without writing" is a normal failure of an unattended
    run and must reach the validation gate with a readable message.
    """
    if not staging.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(destination))
    return True


def validate_system_clock(output_dir: Path) -> tuple:
    """Check system clock sanity by looking for future-dated files.

    If files dated AFTER today already exist, something is wrong:
    either the clock went backwards, or someone/something generated
    future-dated files (e.g. an AI working around a stuck clock).

    Returns (ok: bool, message: str).
    """
    today = datetime.now().date()
    if not output_dir.exists():
        return True, "OK"

    future_files = []
    for f in output_dir.glob("????-??-??.md"):
        try:
            file_date = datetime.strptime(f.stem[:10], "%Y-%m-%d").date()
            if file_date > today:
                future_files.append(f.name)
        except ValueError:
            pass

    if future_files:
        names = ", ".join(sorted(future_files))
        return False, (
            f"System clock anomaly detected: {len(future_files)} future-dated "
            f"file(s) already exist in {output_dir}: {names}. "
            f"Refusing to run — check system clock."
        )

    return True, "OK"


def resolve_output_path(base_path: Path, separator: str = "（", suffix: str = "）") -> Path:
    """Resolve output path, auto-appending (1), (2) if file already exists.

    The first duplicate gets "（1）", second gets "（2）", etc.
    Original file (without number) is never touched — manual runs don't
    overwrite the daily auto-run output.
    """
    if not base_path.exists():
        return base_path

    stem = base_path.stem
    parent = base_path.parent
    suffix_ext = base_path.suffix

    n = 1
    while True:
        candidate = parent / f"{stem}{separator}{n}{suffix}{suffix_ext}"
        if not candidate.exists():
            return candidate
        n += 1
