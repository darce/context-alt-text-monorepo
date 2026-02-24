---
description: Generate CURRENT_TASK.md from handoff DB
---
Run the following to generate CURRENT_TASK.md:
// turbo
make -C $(git rev-parse --show-toplevel) task
