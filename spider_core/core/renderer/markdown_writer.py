"""
Shared report engine — domain-aware routing with atomic writes and backup.

Usage:
    from core.renderer import write_report, ReportWriter

    # Simple one-shot:
    write_report("ai", "# Today's Intel\\n...", report_type="ai")

    # Class-based with frontmatter:
    rw = ReportWriter("cognition")
    rw.set_frontmatter(tags=["cognitive-science", "decision-making"])
    rw.write("# 认知精选\\n...", report_type="cognition")

Output structure (mirrors logs/):
    reports/
    ├── ai/
    │   └── 2026-05-27-ai.md
    └── cognition/
        └── 2026-05-27-cognition.md
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

_yaml_available = True
try:
    import yaml
except ImportError:
    _yaml_available = False


def _fmt_yaml_frontmatter(data: dict[str, Any]) -> str:
    """Build a YAML frontmatter block from a dict."""
    if not data:
        return ""
    if _yaml_available:
        body = yaml.dump(data, allow_unicode=True, default_flow_style=False).strip()
    else:
        lines = []
        for k, v in data.items():
            if isinstance(v, list):
                lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
            else:
                lines.append(f"{k}: {v}")
        body = "\n".join(lines)
    return f"---\n{body}\n---\n"


class ReportWriter:
    """Domain-aware report writer.

    Routes output to reports/{domain}/YYYY-MM-DD-{type}.md.
    Mirrors the log routing pattern: logs/{domain}/YYYY-MM-DD.log.
    """

    def __init__(self, domain: str, base_dir: Path | None = None) -> None:
        self.domain = domain
        self._base = base_dir or Path.cwd() / "reports"
        self._frontmatter: dict[str, Any] = {}
        self._report_dir = self._base / domain
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # -- frontmatter --------------------------------------------------

    def set_frontmatter(self, **fields: Any) -> None:
        """Set YAML frontmatter fields. Merged with existing keys."""
        self._frontmatter.update(fields)

    def clear_frontmatter(self) -> None:
        self._frontmatter.clear()

    # -- write --------------------------------------------------------

    def write(self, content: str, report_type: str = "ai",
              date_str: str | None = None) -> Path:
        """Write a report with atomic write + backup.

        Returns the output path.
        Report failure must never crash the pipeline — caller handles the exception.
        """
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        filename = f"{date_str}-{report_type}.md"
        output_path = self._report_dir / filename

        frontmatter = _fmt_yaml_frontmatter(self._frontmatter)
        full = f"{frontmatter}\n{content}" if frontmatter else content

        # Atomic write: tmp → rename
        tmp_path = output_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(full, encoding="utf-8")

            # Backup existing report before overwriting
            if output_path.exists():
                backup_path = output_path.with_suffix(".md.bak")
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

    # -- path helpers -------------------------------------------------

    def today_path(self, report_type: str = "ai") -> Path:
        """Return the expected path for today's report without writing."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self._report_dir / f"{date_str}-{report_type}.md"

    def latest_report(self, report_type: str = "ai") -> Path | None:
        """Return the most recent report of the given type, or None."""
        pattern = f"*-{report_type}.md"
        candidates = sorted(
            self._report_dir.glob(pattern),
            reverse=True,
        )
        return candidates[0] if candidates else None


def write_report(domain: str, content: str, report_type: str = "ai",
                 base_dir: Path | None = None,
                 frontmatter: dict[str, Any] | None = None) -> Path:
    """One-shot domain-aware report write.

    Routes to reports/{domain}/YYYY-MM-DD-{type}.md.
    Returns the output path.
    """
    rw = ReportWriter(domain, base_dir=base_dir)
    if frontmatter:
        rw.set_frontmatter(**frontmatter)
    return rw.write(content, report_type=report_type)
