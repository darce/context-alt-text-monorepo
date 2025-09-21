# Architecture & Prompt Index

Repo coordination docs, roadmaps, and UML diagrams live under `docs/architecture/`.

## Quick Links

- `docs/architecture/rules/instructions.md` — Engineering principles, layout, testing patterns
- `docs/architecture/rules/tasks.md` — Current sprint tasks, recognition-service backlog prompts, cross-team coordination
- `docs/architecture/rules/roadmap-v3.md` — MVP roadmap and epic status
- `docs/architecture/rules/recognition-service-tasks.md` — Action plan for InsightFace backend integration
- `docs/architecture/backend-uml/` — Backend service diagrams (HF recognition stack)
- `docs/architecture/frontend-uml/` — Frontend/plugin sequence & class diagrams

To edit these from the CLI:

```bash
git checkout -b docs/update-architecture
$EDITOR .docs/architecture/rules/tasks.md
git commit -am "docs: refresh architecture notes"
```

Keep this index in sync whenever new docs are added so contributors and tools can discover the architecture surface quickly.
