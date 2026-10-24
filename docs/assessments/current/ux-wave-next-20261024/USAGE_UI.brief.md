# USAGE_UI remote brief

Read COMMON.md + UI-CONTRACTS.md.

## objective

Display compact read-only authoritative usage and estimate, with separately labelled sitecap and one Usage&billing home.

## finding

19862.

## anchors

Current DescriptionBudgetUsage in settingsApi is local attempts. Existing routingautosave/health stays. Reusable new usagecomponent may be ownedhere; GPU_STATUS alone wires MediaSelection.

## rules

INT-07 Previewbeforecommit (Designing Interfaces3); NAV-05 MECE (Designing Interfaces3); DATA-14 No dualwrites (Designing Data-Intensive Applications ch11); ADR014.

## accept

CONDITIONAL on owner-reviewed tenantreadcontract, independent of API implementationcompletion. nullablecounts remainunknown; period/as_of visible; unavailable vs knowninsufficient separate. Exact chargingpolicycopy from realledger; no onecreditpersuccessfuldescription assumption/topup/providercutover.

## owned paths

- apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx
- apps/prototype-wp-alt-context/js/admin/pages/settings/SettingsForm.tsx

## scoped verification on VM

From apps/prototype-wp-alt-context: npm test -- js/admin/pages/__tests__/SettingsPage.test.tsx js/admin/pages/__tests__/SettingsPage.autosave.test.tsx js/admin/pages/settings/__tests__/SettingsFormNaming.test.tsx; add bounded usagecomponent tests only after DTOqualification.
Then npm run typecheck and narrowly added headless acceptance. Install locked dependencies only in assigned remote sandbox if absent. Never use test:agent because it masks failure. Root reconciles exact lane/counter/subject before dispatch.
