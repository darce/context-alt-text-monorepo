from recognition.application.health import check_health


def test_check_health_returns_ok_report():
    report = check_health()

    assert report.status == "ok"
    assert report.service == "recognition"
    assert report.to_dict()["service"] == "recognition"
