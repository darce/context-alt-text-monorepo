"""Basic health check for the recognition service."""

from shared.health import HealthReport


def check_health() -> HealthReport:
    """Return a static health signal for the recognition service."""
    return HealthReport.ok("recognition")
