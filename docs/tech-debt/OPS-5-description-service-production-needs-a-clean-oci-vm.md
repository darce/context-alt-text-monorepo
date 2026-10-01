# Tech Debt: OPS-5 description-service production needs a clean OCI VM (docker images and volumes unaudited)

**Status:** deferred until the current implementation wave (APP1RB-1 and the DEBTFIX-1 wrap-up) has landed · **Owner:** operator (sudo on `ubuntu@`) + backend (retention policy) · **Origin:** 2026-09-30 disk-pressure session; extends [OPS-1](OPS-1-vm-host-retention-hygiene.md), which covers retention but not a clean production host.

## What was deferred

Production for the description service runs on the same OCI VM (`acx-backend`) that hosts the remote gate clone, lane sandboxes, harness session stores and operator scratch. The goal is a **clean OCI VM for description-service production**, containing only what production needs. First step is an audit of the docker state, which nobody has inspected since OPS-1.

## Evidence (operator-run, 2026-09-30)

`sudo docker system df`:

| Type | Total | Active | Size | Reclaimable |
| --- | --- | --- | --- | --- |
| Images | 13 | 9 | 10.13 GB | 8.39 GB (82 %) |
| Containers | 17 | 17 | 83.3 MB | 0 B |
| Local volumes | 63 | 8 | 11.79 GB | 2.873 GB (24 %) |
| Build cache | 0 | 0 | 0 B | 0 B |

`sudo du -xk --max-depth=2 /` (154 GB total) explains the `df` versus `du` gap the unprivileged `gate` user saw: `/home` 102 GB (`gate` 83 GB, `ubuntu` 19 GB), `/var` 27.7 GB (`/var/lib` 24.2 GB, mostly docker; `/var/log` 3.3 GB), `/tmp` 16.3 GB, `/opt/acx-backend` 4.1 GB. Deleted-but-open files are negligible (largest 12.7 KB), so no process is pinning space.

## Why it's safe to defer

- Disk is at 77 % after the operator reaps (46 GB free), so nothing is at the floor.
- The audit needs `sudo`, and pruning mid-wave risks removing images a running container or a rollback depends on.

## Audit questions

1. Which of the 13 images are the running tags, the rollback tags, and leftovers? 4 are unused and account for the 8.39 GB (82 %) reclaimable; remove by tag, never by age (the OPS-1 trap: an age-based `docker image prune -a` collapsed rollback history).
2. Which of the 55 unattached volumes hold data that matters (postgres, recognition store) and which are orphaned compose leftovers? Name each by owner before removing any.
3. What in `/home/ubuntu` (19 GB), `/home/gate` (83 GB) and `/tmp` (16 GB) is dev, gate or lane scratch that should not live on a production host?
4. Should production move to a dedicated clean OCI VM, with the gate and lane workloads left on the current box, or be cleaned in place? Decide after items 1-3; the dedicated VM is the stated goal.

## Acceptance

- A written inventory of images, volumes and `/home` consumers, each tagged keep, remove or move, signed off by the operator.
- Production serves from a host with no lane sandboxes, no harness session stores and no verify clones.
- A retention job (OPS-1) covers whatever remains on that host.

## Trigger

Pick up when APP1RB-1 and the DEBTFIX-1 wrap-up have merged, or sooner if the VM passes 85 % used again.
