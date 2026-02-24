---
description: CI/local guard for parser + lifecycle + close-check integrity
---
Run the following to verify handoff DB integrity:
// turbo
make -C $(git rev-parse --show-toplevel) handoff-integrity-check
