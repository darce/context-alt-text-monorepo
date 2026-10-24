# USAGE_READ_MODEL remote brief

Read COMMON.md + UI-CONTRACTS.md.

## objective

Qualify tenant-bound authoritative read contract for WP with APP-1 owner; do not duplicate existing portalusage.

## finding

19862.

## anchors

PortalUsageResponse228–243/get_portal_usage1105–1168 already in recognition/interface_adapters/http/routers/portal.py and require interactive portalprincipal. No established WP machine-read route in this packet.

## rules

DATA-14 No dualwrites (Designing Data-Intensive Applications ch11); NAV-05 MECE (Designing Interfaces3); ADR014.

## accept

No source paths granted yet. Root names APP-1 owner, actual auth/route/shape, nullunknown/period/as_of, chargingpolicy. Tests must prove tenantisolation and readsnotspending. No payment/provider/schema/secondledger.

## owned paths

No sourcepath grant; contractqualification only.

## scoped verification on VM

From apps/prototype-wp-alt-context: CONDITIONAL: owner selects existing bounded route/projection tests after exact auth/route/ownership contract is accepted. Do not invent a command for an unselectedendpoint.
Then npm run typecheck and narrowly added headless acceptance. Install locked dependencies only in assigned remote sandbox if absent. Never use test:agent because it masks failure. Root reconciles exact lane/counter/subject before dispatch.
