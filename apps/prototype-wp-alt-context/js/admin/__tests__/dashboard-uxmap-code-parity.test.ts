/**
 * Dashboard UX-map ↔ code fidelity (DUX-W2D14-RV-01..07).
 *
 * A map that names states, labels, or compositions the shell cannot produce
 * is worse than no map. These assertions read the SSOT files and the source
 * strings they claim to describe — they must go red when either side drifts.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  DASHBOARD_FLOW_STATE,
  DASHBOARD_ORIENTATION_POSITION,
  buildDashboardPriorityModel,
  type DashboardPriorityInputs,
} from '../pages/dashboard/buildDashboardPriorityModel';

const here = path.dirname(fileURLToPath(import.meta.url));
const mapsDir = path.resolve(here, '../../../docs/ux-maps');
const adminDir = path.resolve(here, '..');

interface UxZone {
  id: string;
  label: string;
  states?: string[];
}

interface UxScreen {
  id: string;
  kind: string;
  title: string;
  route: string;
  code_ref: string;
  zones?: UxZone[];
  states?: string[];
}

interface UxAction {
  id: string;
  verb: string;
  target: string;
  costly?: boolean;
  preview_required?: boolean;
  screen_id?: string | null;
}

interface UxFlowStep {
  screen_id: string;
  branch_label?: string | null;
}

interface UxFlow {
  id: string;
  steps: UxFlowStep[];
}

interface UxMap {
  screens: UxScreen[];
  actions: UxAction[];
  flows: UxFlow[];
}

const readUtf8 = (relativeFromAdmin: string): string =>
  readFileSync(path.join(adminDir, relativeFromAdmin), 'utf8');

const loadDashboardMap = (): { json: UxMap; md: string } => ({
  json: JSON.parse(readFileSync(path.join(mapsDir, 'dashboard.uxmap.json'), 'utf8')) as UxMap,
  md: readFileSync(path.join(mapsDir, 'dashboard.md'), 'utf8'),
});

const extractSketch = (markdown: string, heading: string): string => {
  const headingIndex = markdown.indexOf(heading);
  expect(headingIndex, `dashboard.md missing heading "${heading}"`).toBeGreaterThan(-1);
  const fence = /```\n([\s\S]*?)```/.exec(markdown.slice(headingIndex));
  expect(fence, `dashboard.md missing ASCII fence after "${heading}"`).toBeTruthy();
  return fence?.[1] ?? '';
};

const sketchControls = (sketch: string): string[] =>
  [...sketch.matchAll(/\[([^\]]+)\]/g)].map((match) => match[1]);

const i18nLiterals = (source: string): string[] =>
  [...source.matchAll(/__\(\s*'((?:\\'|[^'])*)'/g)].map((match) => match[1].replace(/\\'/g, "'"));

/**
 * Extracts the i18n literal from INSIDE the first <h1>...</h1> element only.
 * Bounded to the element so a literal that appears later in the source (e.g.
 * a subtitle, or another __() call after the heading) can never be mistaken
 * for the heading's own text.
 */
const h1Literal = (source: string): string => {
  const openTag = /<h1\b[^>]*>/.exec(source);
  expect(openTag, 'expected an <h1> element').toBeTruthy();
  const contentStart = (openTag?.index ?? 0) + (openTag?.[0].length ?? 0);
  const closeIndex = source.indexOf('</h1>', contentStart);
  expect(closeIndex, 'expected a matching </h1> close tag').toBeGreaterThan(-1);
  const h1Content = source.slice(contentStart, closeIndex);
  const literalMatch = /__\(\s*'([^']+)'/.exec(h1Content);
  expect(literalMatch, 'expected an i18n literal inside the <h1> element').toBeTruthy();
  return literalMatch?.[1] ?? '';
};

describe('dashboard ux-map code parity (DUX-W2D14)', () => {
  const { json, md } = loadDashboardMap();
  const shell = json.screens.find((screen) => screen.id === 'dashboard-shell' && screen.kind === 'screen');
  expect(shell, 'dashboard-shell screen missing').toBeTruthy();

  const zoneById = Object.fromEntries((shell?.zones ?? []).map((zone) => [zone.id, zone]));
  const actionById = Object.fromEntries(json.actions.map((action) => [action.id, action]));

  const dashboardSrc = readUtf8('pages/DashboardPage.tsx');
  const retentionCopySrc = readUtf8('pages/dashboard/retentionCardCopy.ts');
  const orientationSrc = readUtf8('pages/dashboard/OrientationCard.tsx');
  const recentSrc = readUtf8('pages/dashboard/DashboardRecentActivitySection.tsx');
  const guidanceSrc = readUtf8('pages/dashboard/GuidanceCard.tsx');
  const syncSrc = readUtf8('pages/dashboard/DashboardSyncHealthSection.tsx');
  const syncSummarySrc = readUtf8('pages/workbench/degradedModeBannerLogic.ts');

  const basePriorityInputs: DashboardPriorityInputs = {
    isSyncStatusLoading: false,
    isSyncStatusError: false,
    effectiveSyncHealth: 'healthy',
    hasSyncHealthWarnings: false,
    pendingReplayCount: 0,
    conflictCount: 0,
    failedReplayCount: 0,
    topologyPending: 0,
    topologyFailed: 0,
    topologyConflicts: 0,
    showMirrorDivergenceBanner: false,
    isIdentityLoading: false,
    isIdentityError: false,
    hasIdentityStats: true,
    pendingClustersCount: 0,
    unassignedPersonsCount: 0,
    flowState: DASHBOARD_FLOW_STATE.FIRST_NAMED,
  };

  const defaultSketch = extractSketch(md, '#### Default — populated');
  const firstTimeSketch = extractSketch(md, '#### First-time — fresh tenant');
  const loadingSketch = extractSketch(md, '#### Loading');
  const errorSketch = extractSketch(md, '#### Error');
  const degradedSketch = extractSketch(md, '#### Degraded');
  const allSketches = [defaultSketch, firstTimeSketch, loadingSketch, errorSketch, degradedSketch];

  /**
   * The Sync Health section is prose + fences that describe the default branch's
   * modifier axis. It is deliberately NOT part of allSketches: it documents a
   * composition, not a named zone state. RV-16 is what makes its claims falsifiable.
   */
  const syncHealthSection = (() => {
    const start = md.indexOf('#### Sync Health');
    expect(start, 'dashboard.md missing the Sync Health composition section').toBeGreaterThan(-1);
    const next = md.indexOf('\n### ', start);
    return md.slice(start, next === -1 ? undefined : next);
  })();

  it('RV-01: screen/zone/action names come from the rendered component strings', () => {
    const overview = h1Literal(dashboardSrc);
    expect(overview).toBe('Overview');
    expect(i18nLiterals(retentionCopySrc)).toContain('Data Retention');
    expect(i18nLiterals(retentionCopySrc)).toContain('Open Data Retention');

    expect(shell?.title, 'map title must match DashboardPage h1').toBe(overview);
    expect(zoneById['z-retention-posture']?.label).toMatch(/Data Retention/);
    expect(zoneById['z-retention-posture']?.label).not.toMatch(/Retention Posture/);
    expect(actionById['act-open-retention']?.verb).toBe('Open Data Retention');

    expect(defaultSketch).toMatch(/Overview/);
    expect(defaultSketch).not.toMatch(/^\| Dashboard\s+\|$/m);
    expect(defaultSketch).toMatch(/Data Retention/);
    expect(defaultSketch).toMatch(/\[Open Data Retention\]/);
    expect(defaultSketch).not.toMatch(/Retention Posture/);
    expect(defaultSketch).not.toMatch(/\[Retention settings\]/);
  });

  it('RV-10: h1Literal is bound to the <h1> element, not the first literal after it', () => {
    // Hoisting the heading text to a variable removes the only i18n literal
    // inside <h1>...</h1>. An unbounded regex would happily walk past the
    // close tag and capture the later 'Other' literal instead — this must
    // not happen.
    const hoistedHeadingWithLaterLiteral = [
      "const title = 'Some Title';",
      'return (',
      '  <h1>{title}</h1>',
      "  <p>{__('Other', 'alt-context')}</p>",
      ');',
    ].join('\n');

    expect(() => h1Literal(hoistedHeadingWithLaterLiteral)).toThrow();

    // Positive case: a literal after </h1> must never leak into the match
    // when the <h1> element does contain its own literal.
    const properHeadingWithLaterLiteral = [
      "<h1 id=\"x\">{__('Right One', 'alt-context')}</h1>",
      "<p>{__('Other', 'alt-context')}</p>",
    ].join('\n');

    expect(h1Literal(properHeadingWithLaterLiteral)).toBe('Right One');
  });

  it('RV-02: screen states only name exclusive shell branches the code can take', () => {
    const states = shell?.states ?? [];
    expect(states, 'empty is not an exclusive dashboard-shell branch').not.toContain('empty');
    expect(states, 'offline is a Sync Health summary tag, not a shell branch').not.toContain('offline');
    expect(md).not.toMatch(/Screen states:.*\bempty\b/);
    expect(md).not.toMatch(/Screen states:.*\boffline\b/);
    expect(md).not.toMatch(/^#### Empty/m);
    expect(md).not.toMatch(/^#### Offline/m);
  });

  it('RV-03: default and first_time sketches are compositions the priority model can produce', () => {
    expect(
      buildDashboardPriorityModel({ ...basePriorityInputs, flowState: DASHBOARD_FLOW_STATE.FIRST_NAMED })
        .orientationPosition,
      'first_named must hide the orientation surface',
    ).toBe(DASHBOARD_ORIENTATION_POSITION.HIDDEN);
    expect(
      buildDashboardPriorityModel({ ...basePriorityInputs, flowState: DASHBOARD_FLOW_STATE.UNSCANNED })
        .orientationPosition,
      'a non-first_named flow state must keep the orientation surface before the grid',
    ).toBe(DASHBOARD_ORIENTATION_POSITION.BEFORE_GRID);
    expect(
      dashboardSrc,
      'DashboardPage must still derive flowState from assigned_clusters_count',
    ).toMatch(/flowState[\s\S]{0,40}identityStats\?\.assigned_clusters_count[\s\S]{0,40}FIRST_NAMED/);

    const defaultAssigned = Number(/Assigned\s+(\d+)/.exec(defaultSketch)?.[1] ?? '0');
    const firstAssigned = Number(/Assigned\s+(\d+)/.exec(firstTimeSketch)?.[1] ?? '0');

    expect(defaultSketch).not.toMatch(/Getting Started with Identity Recognition/);
    expect(defaultAssigned, 'default sketch must show a named-person (first_named) composition').toBeGreaterThan(0);

    expect(firstTimeSketch).toMatch(/Getting Started with Identity Recognition/);
    expect(firstAssigned, 'first_time sketch must keep assigned at 0 so orientation can show').toBe(0);
    expect(firstTimeSketch).toMatch(/\[Start your first scan\]/);
  });

  it('RV-04: zone state matrices match exclusive component branches', () => {
    expect(recentSrc).toMatch(/historySource === 'unavailable'/);
    expect(zoneById['z-recent-activity']?.states).toEqual(expect.arrayContaining(['default', 'empty', 'degraded', 'error']));
    const unavailableHeadingMatch =
      /EmptyStateVariant\.UNAVAILABLE[\s\S]{0,200}?heading=\{\__\(\s*'((?:\\'|[^'])*)'/.exec(recentSrc);
    expect(unavailableHeadingMatch, 'expected an i18n heading on the UNAVAILABLE EmptyState').toBeTruthy();
    const unavailableHeading = (unavailableHeadingMatch?.[1] ?? '').replace(/\\'/g, "'");
    expect(errorSketch).toContain(unavailableHeading);

    expect(dashboardSrc).toMatch(/acx-dashboard__hero/);
    expect(dashboardSrc).not.toMatch(/hero[\s\S]{0,80}first_time|first_time[\s\S]{0,80}hero/);
    expect(zoneById['z-dashboard-hero']?.states).toEqual(['default']);
    expect(zoneById['z-dashboard-hero']?.states).not.toContain('first_time');

    expect(dashboardSrc).toMatch(/Library Coverage/);
    expect(zoneById['z-library-coverage']?.states).toEqual(['default', 'loading']);
    expect(zoneById['z-library-coverage']?.states).not.toContain('first_time');
  });

  it('RV-05: every sketch control has an action, and every action appears in a sketch', () => {
    expect(i18nLiterals(syncSrc)).toContain('Open Failed Sync Queue');
    expect(i18nLiterals(recentSrc)).toContain('View Results');
    expect(i18nLiterals(dashboardSrc)).toContain('Retry');
    expect(i18nLiterals(orientationSrc)).toContain('Dismiss getting started');
    expect(i18nLiterals(guidanceSrc)).toContain('Go to Review Queue');
    expect(i18nLiterals(guidanceSrc)).toContain('Review unassigned persons');
    expect(i18nLiterals(guidanceSrc)).toContain('Go to Scan tab');

    const requiredActions: Record<string, string> = {
      'act-open-failed-sync': 'Open Failed Sync Queue',
      'act-view-results': 'View Results',
      'act-retry-identity-stats': 'Retry',
      'act-dismiss-orientation': 'Dismiss getting started',
      'act-go-to-review-queue': 'Go to Review Queue',
      'act-review-unassigned': 'Review unassigned persons',
      'act-go-to-scan-tab': 'Go to Scan tab',
    };

    for (const [id, verb] of Object.entries(requiredActions)) {
      expect(actionById[id]?.verb, `${id} missing or misnamed`).toBe(verb);
    }

    const sketchText = allSketches.join('\n');
    const controls = allSketches.flatMap(sketchControls);
    const verbs = new Set(json.actions.map((action) => action.verb));

    expect(sketchText).toMatch(/\[Open Failed Sync Queue\]/);
    expect(controls).toContain('View Results');
    expect(controls).toContain('Retry');
    expect(controls).toContain('Dismiss getting started');
    expect(controls).toContain('Go to Review Queue');
    expect(controls).toContain('Go to Scan tab');
    expect(controls).toContain('Review unassigned persons');

    const unmatched = controls.filter((control) => !verbs.has(control));
    expect(unmatched, `sketch controls with no action entry: ${unmatched.join(', ')}`).toEqual([]);

    const verbsMissingFromSketches = json.actions
      .map((action) => action.verb)
      .filter((verb) => !sketchText.includes(`[${verb}]`));
    expect(
      verbsMissingFromSketches,
      `actions never drawn in a sketch: ${verbsMissingFromSketches.join(', ')}`,
    ).toEqual([]);

    // RV-13: allSketches.join('\n') hides a control missing from one sketch as long as
    // it is present in another. Controls that are genuinely unconditional in the
    // component (rendered outside any loading/error branch) must appear in every
    // sketch where that branch is reachable, checked per sketch, not on the joined text.
    const namedSketches: Record<string, string> = {
      default: defaultSketch,
      first_time: firstTimeSketch,
      loading: loadingSketch,
      error: errorSketch,
      degraded: degradedSketch,
    };

    const unconditionalControls: Record<string, string[]> = {
      // DashboardSyncHealthSection.tsx:122-126 renders 'Open Review Queue' inside the
      // success branch (not isLoading, not isError/!syncStatus). Reachable in every
      // sketch depicting a loaded sync status: default, first_time, degraded.
      'Open Review Queue': ['default', 'first_time', 'degraded'],
      // DashboardPage.tsx:235-245 renders the coverage progress bar and 'Fix missing
      // descriptions' CTA outside the isStatsLoading ternary, so they render in every
      // sketch regardless of loading state.
      'Fix missing descriptions': ['default', 'first_time', 'loading', 'error', 'degraded'],
    };

    for (const [control, expectedIn] of Object.entries(unconditionalControls)) {
      const missingFrom = expectedIn.filter((name) => !sketchControls(namedSketches[name]).includes(control));
      expect(
        missingFrom,
        `${control} is unconditional but missing from sketch(es): ${missingFrom.join(', ')}`,
      ).toEqual([]);
    }
  });

  it('RV-06: off-surface destinations are kind:exit screens and flows land on them', () => {
    const exits = json.screens.filter((screen) => screen.kind === 'exit');
    expect(exits.map((screen) => screen.id).sort()).toEqual(
      ['exit-retention', 'exit-roster', 'exit-workbench'].sort(),
    );

    const workbench = exits.find((screen) => screen.id === 'exit-workbench');
    const retention = exits.find((screen) => screen.id === 'exit-retention');
    const roster = exits.find((screen) => screen.id === 'exit-roster');

    expect(workbench?.route).toBe('#/workbench');
    expect(workbench?.code_ref ?? '').toMatch(/WorkbenchPage\.tsx/);
    expect(retention?.route).toBe('#/retention');
    expect(retention?.title).toBe('Data Retention');
    expect(roster?.route).toBe('#/roster');

    const firstRecognition = json.flows.find((flow) => flow.id === 'flow-first-recognition');
    expect(firstRecognition?.steps.map((step) => step.screen_id)).toContain('exit-workbench');

    const review = json.flows.find((flow) => flow.id === 'flow-dashboard-review');
    expect(review?.steps.map((step) => step.screen_id)).toContain('exit-workbench');

    const maintenance = json.flows.find((flow) => flow.id === 'flow-dashboard-maintenance');
    expect(maintenance?.steps.map((step) => step.screen_id)).toEqual(
      expect.arrayContaining(['exit-workbench', 'exit-retention']),
    );
  });

  it('RV-16: Sync Health composition prose is falsifiable against the component', () => {
    const syncLines = syncSrc.split('\n');
    const lineAt = (oneBased: number): string => syncLines[oneBased - 1] ?? '';

    // (a) Recency copy is a locale calendar date, never relative time. The component
    // formats with toLocaleDateString(); any "N minutes ago" in the map is invented.
    expect(dashboardSrc).toMatch(/toLocaleDateString\(\)/);
    expect(
      syncHealthSection,
      'Sync Health prose must not invent relative recency; the component renders toLocaleDateString()',
    ).not.toMatch(/\b\d+\s+(?:seconds?|minutes?|hours?|days?)\s+ago\b/);

    // (b) Every control drawn in the section is a real i18n literal of the component,
    // and every action label the component ships is accounted for in the section.
    const componentLabels = i18nLiterals(syncSrc);
    // Only the ASCII fences count as "drawn" — prose carries canon citations like
    // [A11Y-24] that are references, not controls.
    const syncFences = [...syncHealthSection.matchAll(/```\n([\s\S]*?)```/g)].map((m) => m[1]);
    expect(syncFences.length, 'Sync Health section must draw at least one composition').toBeGreaterThan(0);
    const drawn = new Set(syncFences.flatMap((fence) => sketchControls(fence)));
    expect(drawn.size, 'Sync Health section must draw its controls').toBeGreaterThan(0);
    for (const control of drawn) {
      expect(componentLabels, `sketch control "${control}" is not an i18n literal of the component`).toContain(
        control,
      );
    }
    const shippedActions = componentLabels.filter(
      (label) => label === 'Reset mirror' || label.startsWith('Open '),
    );
    expect(shippedActions.length, 'expected the component to ship named actions').toBeGreaterThan(0);
    for (const action of shippedActions) {
      expect(
        syncHealthSection,
        `component ships "${action}" but the Sync Health section never names it`,
      ).toContain(action);
    }

    // (c) Every ":NNN predicate" cite in the member table resolves at that exact line.
    const cites = [...syncHealthSection.matchAll(/^ {4}\S+\s+:(\d+)\s+(\S+)/gm)];
    expect(cites.length, 'member table must carry line cites').toBeGreaterThanOrEqual(6);
    for (const [, rawLine, predicate] of cites) {
      const lineNo = Number(rawLine);
      expect(lineAt(lineNo), `cited line ${lineNo} is past the end of the component`).not.toBe('');
      if (predicate.startsWith('(')) {
        continue;
      }
      const identifier = /[A-Za-z_][A-Za-z0-9_]*/.exec(predicate)?.[0] ?? '';
      expect(
        lineAt(lineNo).replace(/\s+/g, ''),
        `map cites :${lineNo} for "${predicate}" but that line does not mention ${identifier}`,
      ).toContain(identifier);
    }

    // The three unconditional members are cited by the markers they actually render.
    expect(lineAt(152)).toContain('acx-dashboard-sync-summary');
    expect(lineAt(155)).toContain('acx-dashboard__stats-grid');
    expect(lineAt(185)).toContain('acx-dashboard__actions');

    // (d) A recency line and its CTA are gated separately — this is the claim the map
    // previously got wrong. The CTA gate must NOT require a date.
    expect(lineAt(179).replace(/\s+/g, '')).toContain('conflictCount>0&&lastConflictDate');
    expect(lineAt(190).replace(/\s+/g, '')).toContain('conflictCount>0?');
    expect(lineAt(190)).not.toContain('lastConflictDate');
    expect(lineAt(196).replace(/\s+/g, '')).toContain('failedReplayCount>0?');
    expect(lineAt(196)).not.toContain('lastFailureDate');

    // (e) The SyncHealth cases the prose enumerates are exactly the selector's cases.
    const selectorCases = [...syncSummarySrc.matchAll(/case '([a-z]+)':/g)].map((m) => m[1]);
    expect(selectorCases.length, 'expected getDashboardSyncHealthSummary to switch on SyncHealth').toBeGreaterThan(0);
    const claimed = /six `SyncHealth` cases \(([^)]*)\)/.exec(syncHealthSection);
    expect(claimed, 'Sync Health prose must enumerate the summary cases it claims').toBeTruthy();
    const claimedNames = (claimed?.[1] ?? '')
      .split(',')
      .map((part) => /[a-z]+/.exec(part.trim())?.[0] ?? '')
      .filter(Boolean);
    expect([...claimedNames].sort(), 'enumerated cases must match the selector exactly').toEqual(
      [...new Set(selectorCases)].sort(),
    );
  });

  it('RV-07: act-start-first-scan is a hash navigation, not a costly scan commit', () => {
    expect(orientationSrc).toMatch(/toWorkbench\(\{\s*tab:\s*'scan'\s*\}\)/);
    expect(orientationSrc).toMatch(/Start your first scan/);

    const start = actionById['act-start-first-scan'];
    expect(start?.verb).toBe('Start your first scan');
    expect(start?.costly, 'hash link must not be flagged costly').toBe(false);
    expect(start?.preview_required, 'hash link must not require a cost preview').toBe(false);
  });
});
