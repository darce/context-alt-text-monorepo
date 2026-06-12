# Demo seed media bundle

Deterministic seed images for the public demo walkthrough. Every face file in
`media/` must have documented provenance before the demo DNS goes public.

## Provenance requirements

- Use **generated** or **public-domain** faces only — no stock photos without
  explicit commercial/demo rights.
- Record source, license, and capture date in the table below before import.
- A public demo with unlicensed faces is a launch blocker independent of code readiness.

| File | Subject label (for assertions) | Source / license | Added |
| --- | --- | --- | --- |
| _(operator fills)_ | | | |

## Layout

```text
infra/oci/demo/seed/
  README.md          this file
  import.sh          wp-cli import (run on VM or via bootstrap)
  media/             JPEG/PNG inputs (not committed until licensed)
```

Place 5–10 recognizable face images under `media/` before running `import.sh`.
The walkthrough runbook names expected roster labels for E2E assertions.

## Import

On the VM after bootstrap:

```bash
cd /opt/acx-backend/demo
./seed/import.sh
```

Or from repo checkout during development:

```bash
DEMO_DIR=/opt/acx-backend/demo ./infra/oci/demo/seed/import.sh
```
