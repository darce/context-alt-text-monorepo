from shared.health import HealthReport


def check_health() -> HealthReport:
    """Return a static health signal for the scene service."""
    return HealthReport.ok("scene")
