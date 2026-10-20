"""Spider shared output engines — domain-aware routing, atomic writes, three-layer output."""

from core.renderer.markdown_writer import ReportWriter, write_report
from core.renderer.health_writer import HealthWriter, write_health

__all__ = ["ReportWriter", "write_report", "HealthWriter", "write_health"]
