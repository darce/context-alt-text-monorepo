# demolive-8 — `/health/detailed` `description_adapter`

Lane: `demolive-8`  
Task: `DEMOLIVE-8` / R1-05  
Worktree sandbox: `feature-demolive-8-0537e3e7`

## Contract

| Item | Value |
| --- | --- |
| JSON key | `description_adapter` (top-level string on `GET /health/detailed`) |
| Settings symbol | `DescriptionSettings.profile` (`scene.config.settings.DescriptionSettings`) |
| Emitted as | `description_settings.profile.value` (`DescriptionProfile` StrEnum, sr-007) |
| Resolved when | once in `register_health_probes`, closed over; not re-read from `os.environ` per request |
| Env source (existing) | `ACX_DESCRIPTION_ADAPTER` via `DescriptionSettings` default_factory; no new env var |
| `/health` | unchanged; liveness still omits `description_adapter` |
| Additive | existing `/health/detailed` keys retained (`status`, `timestamp`, `pool_stats`, `breaker_state`, `model_cache`, `embedding_runtime`) |

Test file: `apps/prototype-description-service/recognition/tests/api/test_health_probes.py`  
Test: `test_health_detailed_reports_description_adapter` parametrized `seeded` and `florence_small`.

## Mutation evidence

A green test is not evidence. After the implementation was green, the payload field was hardcoded:

```python
"description_adapter": "seeded",
```

Then:

```
cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/api/test_health_probes.py::test_health_detailed_reports_description_adapter -q
```

### Verbatim failure

```
.F                                                                       [100%]
=================================== FAILURES ===================================
_______ test_health_detailed_reports_description_adapter[florence_small] _______

profile = 'florence_small'
tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-2425/test_health_detailed_reports_d1')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0xffbc047c84d0>

    @pytest.mark.parametrize("profile", ["seeded", "florence_small"])
    def test_health_detailed_reports_description_adapter(profile: str, tmp_path, monkeypatch) -> None:
        """Auth-gated diagnostic must expose the active description profile.
    
        model_cache.profile is the face_pipeline profile. The demo describe gate
        needs the caption producer — DescriptionSettings.profile — as a top-level
        string. Parametrize two real profiles so a hardcoded field fails.
        """
        from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
        from scene.config.settings import DescriptionSettings
    
        monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", profile)
    
        bundle = tmp_path / "buffalo_l"
        bundle.mkdir()
        (bundle / "det_10g.onnx").write_bytes(b"stub")
    
        app = _build_ready_app(model_cache_dir=tmp_path)
    
        async def _auth_ok() -> AuthContext:
            return AuthContext(token=None, tenant_claim=None, enabled=False)
    
        app.dependency_overrides[require_auth] = _auth_ok
        client = TestClient(app)
    
        resp = client.get("/health/detailed")
        assert resp.status_code == 200, resp.text
        body = resp.json()
>       assert body["description_adapter"] == profile
E       AssertionError: assert 'seeded' == 'florence_small'
E         
E         - florence_small
E         + seeded

recognition/tests/api/test_health_probes.py:342: AssertionError
------------------------------ Captured log call -------------------------------
INFO     httpx:_client.py:1025 HTTP Request: GET http://testserver/health/detailed "HTTP/1.1 200 OK"
=========================== short test summary info ============================
FAILED recognition/tests/api/test_health_probes.py::test_health_detailed_reports_description_adapter[florence_small] - AssertionError: assert 'seeded' == 'florence_small'
  
  - florence_small
  + seeded
1 failed, 1 passed in 1.05s
```

### Revert

Hardcode reverted to:

```python
"description_adapter": description_adapter,
```

where `description_adapter = description_settings.profile.value` and `description_settings = DescriptionSettings()` at registration.

Post-revert: `uv run --extra dev pytest recognition/tests/api/test_health_probes.py -q` → `28 passed`. Mutation is not in the tree.
