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

## Round 2 — verification

Round 1 never executed pytest: `uv run --extra dev pytest` was invoked from the worktree root, where extra `dev` is undefined (exit 2). This round ran the tests from the service directory.

### Commands and results

```
cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/api/test_health_probes.py -q
```

```
............................                                             [100%]
28 passed in 8.14s
EXIT_CODE=0
```

Broader api package (green, so this was required):

```
cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/api -q
```

```
........................................................................ [ 17%]
........................................................................ [ 34%]
........................................................................ [ 52%]
........................................................................ [ 69%]
........................................................................ [ 87%]
....................................................                     [100%]
412 passed in 176.72s (0:02:56)
EXIT_CODE=0
```

No production edits. `api/main.py` and `test_health_probes.py` were already correct.

### TEST-15 mutation 1 — omit the field

Removed `"description_adapter": description_adapter` from the `/health/detailed` response dict in `api/main.py`. Re-ran the test file.

```
cd apps/prototype-description-service && uv run --extra dev pytest recognition/tests/api/test_health_probes.py -q
```

Verbatim FAIL (both parametrized cases):

```
>       assert body["description_adapter"] == profile
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'description_adapter'

recognition/tests/api/test_health_probes.py:342: KeyError
```

Summary tail:

```
FAILED recognition/tests/api/test_health_probes.py::test_health_detailed_reports_description_adapter[seeded] - KeyError: 'description_adapter'
FAILED recognition/tests/api/test_health_probes.py::test_health_detailed_reports_description_adapter[florence_small] - KeyError: 'description_adapter'
2 failed, 26 passed in 7.63s
EXIT_CODE=1
```

Reverted the field. Re-run: `28 passed in 7.87s`, `EXIT_CODE=0`.

### TEST-15 mutation 2 — hardcode `"seeded"`

Changed `description_adapter = description_settings.profile.value` to `description_adapter = "seeded"`. Re-ran the test file.

Verbatim FAIL (`florence_small` only; `seeded` stayed green):

```
>       assert body["description_adapter"] == profile
E       AssertionError: assert 'seeded' == 'florence_small'
E
E         - florence_small
E         + seeded

recognition/tests/api/test_health_probes.py:342: AssertionError
```

Summary tail:

```
FAILED recognition/tests/api/test_health_probes.py::test_health_detailed_reports_description_adapter[florence_small] - AssertionError: assert 'seeded' == 'florence_small'

  - florence_small
  + seeded
1 failed, 27 passed in 7.70s
EXIT_CODE=1
```

Reverted to `description_settings.profile.value`. Re-run: `28 passed in 7.42s`, `EXIT_CODE=0`.

Neither mutation stayed green. The test is not decoration. Final tree has no mutation (`git diff` on `api/main.py` empty).

### Settings-hoist divergence (read-only; hoist unchanged)

**Yes — caption-producing paths construct their own `DescriptionSettings()` at request time.** The probe can diverge from the adapter that actually captions.

Hoist (closed over once):

- `apps/prototype-description-service/api/main.py:356-357` — `description_settings = DescriptionSettings()` then `description_adapter = description_settings.profile.value`
- `apps/prototype-description-service/api/main.py:492` — payload emits the closed-over string

Caption paths (new `DescriptionSettings()` per call; no `lru_cache` on these resolvers):

- `apps/prototype-description-service/scene/interface_adapters/http/deps.py:169` — `get_description_adapter()` (`settings = DescriptionSettings()` then `get_profile_spec(settings.profile)`). Wired as FastAPI `Depends(get_description_adapter)` on the describe routes.
- `deps.py:86` — `get_gpu_description_adapter()`
- `deps.py:135` — `get_cpu_description_adapter()`
- `deps.py:234` — `get_async_gpu_description_adapter()`
- `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:511` — `describe_image_multipart` constructs `settings = DescriptionSettings()` after `request.form()`, then may call `get_gpu_description_adapter()` / `get_cpu_description_adapter()` at `describe.py:543-545`
- `describe.py:668` — `enqueue_describe_image` constructs `settings = DescriptionSettings()`
- `apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py:106-107` — `_build_describe_one` calls `get_description_adapter()` then `DescriptionSettings()`

`DescriptionSettings.profile` is a `Field(default_factory=lambda: DescriptionProfile(os.environ.get("ACX_DESCRIPTION_ADAPTER", "seeded")))` at `scene/config/settings.py:32-33`. Each construction re-reads env.

If `ACX_DESCRIPTION_ADAPTER` changes after `register_health_probes` without a process restart, `/health/detailed` still reports the registration snapshot while `get_description_adapter()` builds a different adapter. That reintroduces R1-05's false coupling one layer in: the demo gate would trust the probe while captions come from another profile.

Normal production (env set at process start, never mutated) matches. Hoist left unchanged this round as ordered.
