# Subagent Bridge Interface Note

The orchestration layer depends on a very small execution seam:

```python
def run_subagent(
    prompt: str,
    schema: dict,
    cwd: str,
    env: dict | None = None,
) -> dict | str: ...
```

That seam is intentionally host-oriented rather than Codex-specific. A non-Codex
adapter can fit without changing `lane_exec.py` or `review_runner.py` as long as it:

- accepts the fully rendered prompt
- constrains or validates final output against the supplied JSON schema
- executes in the requested worktree `cwd`
- treats `env` as optional local runtime hints, not as permission to mutate MCP state
- returns either a Python `dict` or a JSON string that parses into one

Minimal non-Codex example:

```python
def run_subagent(prompt: str, schema: dict, cwd: str, env: dict | None = None) -> dict:
    client = KimiHostClient(cwd=cwd, env=env)
    try:
        client.connect()
        return client.run_structured_prompt(prompt=prompt, output_schema=schema)
    finally:
        client.close()
```

What should stay outside any bridge implementation:

- MCP handoff writes
- review finding persistence
- lane routing or manifest logic
- result-schema ownership

Those responsibilities remain in the parent daemon process so bridges stay portable
and easy to swap.
