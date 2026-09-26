from __future__ import annotations

import pytest

from test_enable_public_guide import _log, _mutations, _run


@pytest.mark.parametrize("runner_env", [None, "host"])
def test_host_runner_refuses_remote_site_before_mutating_local_wordpress(
    tmp_path, runner_env: str | None
) -> None:
    extra_env = {} if runner_env is None else {"ACX_WP_RUNNER": runner_env}
    result = _run(tmp_path, site_url="https://demo.altcontext.com", extra_env=extra_env)
    output = result.stdout + result.stderr

    assert result.returncode == 2, output
    assert "ACX_WP_RUNNER=host cannot target a remote SITE_URL" in output
    assert _mutations(tmp_path) == ""
    assert "wp " not in _log(tmp_path)
    assert "curl " not in _log(tmp_path)
