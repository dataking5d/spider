"""
Spider Version Manager
======================
Reads the current version from versions/spider_versions.md,
auto-increments, and appends a new version entry.

Usage:
  python version.py "Fixed PATH issue" "Added network retry" "Added offline retry support"

The script will:
  1. Parse existing versions to find the latest version number
  2. Increment (e.g. v0.2 -> v0.3)
  3. Prepend (or append) the new entry with today's date
  4. Keep markdown formatting clean
"""
import sys
import re
import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VERSIONS_FILE = BASE_DIR / "versions" / "spider_versions.md"


def get_latest_version(text: str) -> tuple[int, int]:
    """Return (major, minor) of the latest version found in the file."""
    matches = re.findall(r"## Spider v(\d+)\.(\d+)", text)
    if not matches:
        return 0, 0
    # Sort by major then minor, take highest
    versions = [(int(m[0]), int(m[1])) for m in matches]
    versions.sort()
    return versions[-1]


def format_entry(version_str: str, changes: list[str], date_str: str) -> str:
    """Build a single version entry block."""
    lines = [f"## Spider {version_str}", ""]
    for c in changes:
        lines.append(f"- {c}")
    lines.append("")
    lines.append(f"日期：{date_str}")
    lines.append("")
    return "\n".join(lines)


def append_version(changes: list[str]) -> str:
    """Append a new version entry to the versions file. Returns the new version string."""
    if VERSIONS_FILE.exists():
        content = VERSIONS_FILE.read_text(encoding="utf-8")
    else:
        content = "# 小蜘蛛成长日志\n\n> 记录 Spider 每一次功能进化，保留完整的成长轨迹。\n> 由 `version.py` 自动维护，也可手动编辑。\n\n---\n"

    major, minor = get_latest_version(content)
    new_minor = minor + 1
    new_version = f"v{major}.{new_minor}"
    today = datetime.now().strftime("%Y-%m-%d")

    entry = format_entry(new_version, changes, today)

    # Insert after the header separator (first ---), keeping latest at top
    parts = content.split("---\n", 1)
    if len(parts) == 2:
        new_content = parts[0] + "---\n\n" + entry + "---\n\n" + parts[1].lstrip()
    else:
        new_content = content.rstrip() + "\n\n" + entry + "\n"

    VERSIONS_FILE.write_text(new_content, encoding="utf-8")

    # Print for caller
    for line in entry.split("\n"):
        print(f"[VERSION] {line}")
    return new_version


def show_history():
    """Print the full version history."""
    if VERSIONS_FILE.exists():
        print(VERSIONS_FILE.read_text(encoding="utf-8"))
    else:
        print("No version history yet. Run with changes to create the first entry.")


# ── CLI ──────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python version.py <change 1> [change 2] ...")
        print("       python version.py --show   (view full history)")
        sys.exit(0)

    if sys.argv[1] == "--show":
        show_history()
    else:
        changes = sys.argv[1:]
        new_ver = append_version(changes)
        print(f"\n  版本记录完成: Spider {new_ver}")
