from shared.health import HealthReport


def check_health() -> HealthReport:
    """Return a static health signal for the roster service."""
    return HealthReport.ok("roster")
