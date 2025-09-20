# Context Alt Text Monorepo

This repository tracks both halves of the Context Alt Text project:

- `apps/wp-context-alt-text/` — the WordPress plugin surface (greenfield rebuild).
- `apps/recognition-service/` — the Hugging Face/CPU deployment that provides scene analysis, embeddings, and roster APIs.
- `packages/` — shared contracts and tooling that must stay in sync across services.
- `docs/architecture/` — authoritative roadmap, diagrams, and engineering process.

## Working with LocalWP

The plugin source of truth lives in `apps/wp-context-alt-text/`. To run it inside a LocalWP instance:

```bash
# from the LocalWP site root (e.g., ~/Development/wp-context-alt-text/app/public/wp-content/plugins)
rm -rf context-alt-text
ln -s ../../../../../context-alt-text/apps/wp-context-alt-text context-alt-text
```

Keep all plugin changes on the monorepo side; the LocalWP folder only contains the symlink and should not be committed.

## Recognition Service Remotes

The FastAPI recognition service needs multiple remotes:

```bash
cd apps/recognition-service
# GitHub backup
git remote add origin git@github.com:<user>/context-alt-text-recognition.git
# Hugging Face deployment (for Spaces CI/CD)
git remote add hf https://huggingface.co/spaces/<user>/context-alt-text-recognition
```

Push to GitHub for backup and code review, then push the same branch to `hf` for deployment.

## Suggested Directory Layout

```
apps/
  wp-context-alt-text/          # plugin source
  recognition-service/          # FastAPI backend
packages/
  shared-contracts/             # JSON schemas, DTOs
  wp-testing-helpers/           # reusable test utilities
.tools/
  scripts/                      # local dev scripts
docs/architecture/             # roadmap + UML (do not delete)
```

As the rebuild progresses, move any shared JSON schemas or PHP/TS DTO definitions into `packages/shared-contracts` so both apps import from the same source.

## Contributing Workflow

1. Make changes under the relevant `apps/` directory.
2. Update shared contracts/tests in `packages/` when API shapes change.
3. Refresh architecture docs under `docs/` (roadmap status, UML) before merging.
4. Run service-specific test suites (`composer test`, `npm test`, `pytest`) from each app.
5. Commit from the repository root so history reflects coordinated changes.
