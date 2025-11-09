from shared.health import HealthReport


def check_health() -> HealthReport:
    """Return a static health signal for the recognition service."""
    # Future implementations can inject database or model checks here.
    return HealthReport.ok("recognition")
