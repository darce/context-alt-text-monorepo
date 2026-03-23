# Branch Review — Python / FastAPI / SQLAlchemy

> Load this guide when the branch diff includes files under `apps/prototype-description-service/`.
> For universal process, severity definitions, and report template see [branch-review-guide.md](branch-review-guide.md).

---

## Automated Checks

Backend review commands must run inside the `description-service` pyenv. For non-interactive commands, prefer `PYENV_VERSION=description-service <command>` instead of relying on `pyenv activate`, because subprocess shells may not have pyenv init hooks loaded.

| Check                    | Command                                                      |
| ------------------------ | ------------------------------------------------------------ |
| Lint + types + tests     | `cd apps/prototype-description-service && PYENV_VERSION=description-service make check`        |
| Cyclomatic complexity    | `cd apps/prototype-description-service && PYENV_VERSION=description-service python -m radon cc --min C --show-complexity --average recognition/` |

---

## Type Safety

- [ ] No `object` parameters — use the domain type or a Protocol.
- [ ] No `getattr()` + `callable()` guards — declare methods on the Protocol.
- [ ] No `contextlib.suppress(Exception)` — catch specific exceptions and log.
- [ ] `assert` used only for internal invariants/tests — request validation and external-data checks use explicit exceptions or HTTP errors.

---

## Architecture Boundaries

- [ ] **No raw SQL in the application layer** — `text()` calls only in `infrastructure/repositories/`.
- [ ] **No presentation DTOs in domain or application layer** — API response shapes in `interface_adapters/schemas/`.
- [ ] **No default-instantiating settings** — inject via DI, don't construct defaults inside functions.
- [ ] **No cross-layer exception duplication** — one canonical definition per exception.
- [ ] **No redundant router/dependency wiring** — each router registered exactly once.
- [ ] **No time-based gates on curated state** — gate on data deltas, never elapsed time.

---

## Error Handling

- [ ] **LIKE wildcard escaping** — user-supplied strings in `ilike()` escape `%` and `_`.
- [ ] **No bare exception suppression** — `except Exception` logs at `WARNING` minimum.
- [ ] **Scoped exception clauses** — `try/except` wraps only the single operation it guards.
- [ ] **Consistent gate fallbacks** — all bypass paths apply the same checks (blocks AND constraints).

---

## Code Duplication

- [ ] **Shared repository utilities** — UUID coercion, media-identity bootstrap in `_helpers.py`.
- [ ] **Shared test stubs** — Protocol stubs used in 3+ files extracted to `tests/stubs.py`.
- [ ] **One canonical fake per protocol** — no divergent fakes across test files.
- [ ] **No duplicate methods** — Protocol interfaces have no aliased methods.

---

## Metric Thresholds

### Function Size

| Metric                  | Target | Max | Resolution                         |
| ----------------------- | ------ | --- | ---------------------------------- |
| Lines per function      | < 30   | 40  | Extract helper functions           |
| Parameters per function | < 5    | 7   | Use a parameter object / dataclass |

### Cyclomatic Complexity (radon)

| Grade   | Range | Action                                              |
| ------- | ----- | --------------------------------------------------- |
| **A**   | 1–5   | No action needed.                                   |
| **B**   | 6–10  | Acceptable. Review if function could be simplified. |
| **C**   | 11–15 | **Requires justification.** Flag in review.         |
| **D**   | 16–20 | **Must refactor.**                                  |
| **E/F** | 21+   | **Block merge.**                                    |

Typical offenders: Repository `_to_domain` converters, refresh service orchestration methods, clustering dispatch functions.

---

## Complexity Tooling

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "radon>=6.0.0",
]
```

Makefile target:

```makefile
complexity:
	$(ACTIVATE) && python -m radon cc --min C --show-complexity --average recognition/
```
