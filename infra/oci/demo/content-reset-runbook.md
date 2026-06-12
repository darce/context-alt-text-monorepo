# Optional demo content reset runbook

Use between beta cohorts to restore a known-good demo state without touching
recognition API data.

## When to run

- After exploratory tester sessions that mutate demo media/rosters
- Before a recorded walkthrough when content drifted
- **Not** on a schedule that overlaps live visitor traffic without notice

## Preconditions

- Latest `dist/alt-context-<version>.zip` available on the VM (or re-ship via
  `make deploy-demo`)
- `secrets/.env` unchanged unless intentionally rotating credentials
- Seed import script (Slice 3) may re-run after this reset

## Soft reset (content only)

From `/opt/acx-backend/demo`:

```bash
docker compose -f docker-compose.demo.yml exec -T wordpress \
  wp post delete $(wp post list --post_type=post --format=ids) --force
docker compose -f docker-compose.demo.yml exec -T wordpress \
  wp media regenerate --yes
```

Replace with the Slice 3 seed import once media is licensed:

```bash
cd /opt/acx-backend/demo
./seed/import.sh
```

## Hard reset (reinstall WP + plugin)

Destructive to demo volumes only — never run `-v` flags that touch shared
`/opt/acx-backend/data/prod-*` paths.

```bash
sudo systemctl stop acx-demo
sudo rm -rf /opt/acx-backend/data/demo-wpdata/* /opt/acx-backend/data/demo-dbdata/*
sudo systemctl start acx-demo
PLUGIN_ZIP=/tmp/alt-context.zip ./bootstrap-wp.sh
```

## Nightly automation (optional)

If enabled, wrap the soft reset in a systemd timer owned by the operator.
Document the schedule in the run log; default repo posture leaves this manual.
