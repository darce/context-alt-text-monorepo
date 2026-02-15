# Testing Guides

Testing documentation is now split by language/framework for focused context loading:

## Quick Navigation

**Start here for universal concepts:**  
→ [testing-principles.md](testing-principles.md)

**Then choose your language:**

- TypeScript / React / Vitest → [testing-typescript.md](testing-typescript.md)
- Python / pytest / FastAPI → [testing-python.md](testing-python.md)  
- PHP / PHPUnit / WordPress → [testing-php.md](testing-php.md)

## Why Split?

The old consolidated `testing-standards.md` mixed PHP, Python, and TypeScript patterns in a single 320-line file. This forced agents to ingest irrelevant context (e.g., loading React hooks patterns when writing Python tests).

The split structure:
- Reduces token usage (only load relevant language guide)
- Improves discoverability (clear file names)
- Enables TDD workflow (testing guides loaded alongside role guidelines)
- Makes updates easier (change PHP rules without touching TS rules)

## Migration Note

The old consolidated file is preserved as `archived-testing-standards-legacy.md` for reference.
