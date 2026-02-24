---
description: Validate that active handoff state is ready to close
---
Run the following to enforce close-readiness on active handoff task:
// turbo
make -C $(git rev-parse --show-toplevel) handoff-close-check
