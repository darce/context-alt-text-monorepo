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


## Repository Management

This monorepo is the single source of truth for both the plugin and the recognition service.

```bash
# clone once
git clone git@github.com:darce/context-alt-text-monorepo.git

# work from feature branches at the root
git checkout -b feature/<short-description>

# commit from the root so frontend + backend changes land together
git add apps/ packages/ docs/
git commit -m "feat: ..."
```

Avoid nested Git repositories or submodules inside `apps/`. If a legacy `.git` directory exists (for example under `apps/recognition-service`), remove it so all history is captured by the root repo.

## Deploying the Recognition Service to Hugging Face

The Space should mirror `apps/recognition-service`. After CI passes on `main`, push the subtree to Hugging Face:

```bash
# add once
git remote add hf git@hf.co:spaces/dearce/recognition-service

# publish the latest main branch
git subtree push --prefix=apps/recognition-service hf main
```

Automate this flow with GitHub Actions: run pytest for the backend, then execute the subtree push whenever `main` is updated.



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
