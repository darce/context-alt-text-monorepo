import { describe, expect, it } from 'vitest';

import {
  APP_LINK_PARAMS,
  APP_LINK_VALUES,
  SCAN_CONFLICTS_HREF,
  SCAN_DEAD_LETTER_HREF,
  buildWorkbenchOverlayHref,
  parsePanes,
  parseRunParam,
  serializePanes,
  serializeRunParam,
  toDashboard,
  toDescriptionHistory,
  toDescriptionHistoryRun,
  toRetention,
  toRoster,
  toRosterPerson,
  toWorkbench,
  type PanesState,
} from '../appLinks';

/** Parse a contract href into path + URLSearchParams (round-trip helper). */
const parseHref = (hashHref: string): { path: string; params: URLSearchParams } => {
  expect(hashHref.startsWith('#/')).toBe(true);
  const withoutHash = hashHref.slice(1);
  const q = withoutHash.indexOf('?');
  if (q === -1) {
    return { path: withoutHash, params: new URLSearchParams() };
  }
  return {
    path: withoutHash.slice(0, q),
    params: new URLSearchParams(withoutHash.slice(q + 1)),
  };
};

describe('appLinks builders', () => {
  it('toDashboard / toRetention / toDescriptionHistory emit bare routes', () => {
    expect(toDashboard()).toBe('#/dashboard');
    expect(toRetention()).toBe('#/retention');
    expect(toDescriptionHistory()).toBe('#/description-history');
  });

  it('toWorkbench emits empty workbench and typed option shapes', () => {
    expect(toWorkbench()).toBe('#/workbench');
    expect(toWorkbench({ status: 'missing' })).toBe('#/workbench?status=missing');
    expect(toWorkbench({ tab: 'scan' })).toBe('#/workbench?tab=scan');
    expect(toWorkbench({ advanced: true })).toBe('#/workbench?advanced=open');
    expect(toWorkbench({ advanced: APP_LINK_VALUES.advancedOpen })).toBe(
      '#/workbench?advanced=open',
    );
    expect(toWorkbench({ tab: 'scan', panel: 'conflicts' })).toBe(
      '#/workbench?tab=scan&panel=conflicts',
    );
  });

  it('toWorkbench round-trips option objects through hash query params', () => {
    const href = toWorkbench({
      tab: 'scan',
      panel: 'dead-letter',
      advanced: true,
      status: 'missing',
    });
    const { path, params } = parseHref(href);
    expect(path).toBe('/workbench');
    expect(params.get(APP_LINK_PARAMS.tab)).toBe('scan');
    expect(params.get(APP_LINK_PARAMS.panel)).toBe('dead-letter');
    expect(params.get(APP_LINK_PARAMS.advanced)).toBe(APP_LINK_VALUES.advancedOpen);
    expect(params.get(APP_LINK_PARAMS.status)).toBe('missing');
  });

  it('toRoster / toRosterPerson emit personFilter and person deep-links', () => {
    expect(toRoster()).toBe('#/roster');
    expect(toRoster({ personFilter: 'unassigned' })).toBe('#/roster?personFilter=unassigned');
    expect(toRosterPerson('uuid-abc')).toBe('#/roster?person=uuid-abc');

    const { path, params } = parseHref(toRosterPerson('person-1'));
    expect(path).toBe('/roster');
    expect(params.get(APP_LINK_PARAMS.person)).toBe('person-1');
  });

  it('toDescriptionHistoryRun round-trips run ids (including reserved chars)', () => {
    expect(toDescriptionHistoryRun('run-42')).toBe('#/description-history?run=run-42');
    const encoded = toDescriptionHistoryRun('a b/c');
    const { path, params } = parseHref(encoded);
    expect(path).toBe('/description-history');
    expect(params.get(APP_LINK_PARAMS.run)).toBe('a b/c');
    expect(parseRunParam(params.get(APP_LINK_PARAMS.run))).toBe('a b/c');
  });

  it('toDescriptionHistoryRun routes empty/whitespace through serializeRunParam (build/parse symmetry)', () => {
    // Empty/whitespace → omit run (list surface); parse of emitted href stays null.
    for (const emptyId of ['', '   ', '\t']) {
      const href = toDescriptionHistoryRun(emptyId);
      expect(href).toBe('#/description-history');
      const { params } = parseHref(href);
      expect(params.get(APP_LINK_PARAMS.run)).toBeNull();
      expect(parseRunParam(params.get(APP_LINK_PARAMS.run))).toBeNull();
      expect(parseRunParam(serializeRunParam(emptyId))).toBeNull();
    }
    // Non-empty trims then round-trips via the same codec path the builder uses.
    const trimmed = toDescriptionHistoryRun('  run-x  ');
    const { params: trimmedParams } = parseHref(trimmed);
    expect(trimmedParams.get(APP_LINK_PARAMS.run)).toBe('run-x');
    expect(parseRunParam(trimmedParams.get(APP_LINK_PARAMS.run))).toBe('run-x');
  });

  it('folded overlay helpers preserve pre-contract href shapes', () => {
    expect(buildWorkbenchOverlayHref('scan', 'conflicts')).toBe(
      '#/workbench?tab=scan&panel=conflicts',
    );
    expect(buildWorkbenchOverlayHref('scan', 'dead-letter')).toBe(
      '#/workbench?tab=scan&panel=dead-letter',
    );
    expect(SCAN_CONFLICTS_HREF).toBe('#/workbench?tab=scan&panel=conflicts');
    expect(SCAN_DEAD_LETTER_HREF).toBe('#/workbench?tab=scan&panel=dead-letter');
    expect(SCAN_CONFLICTS_HREF).toBe(toWorkbench({ tab: 'scan', panel: 'conflicts' }));
    expect(SCAN_DEAD_LETTER_HREF).toBe(toWorkbench({ tab: 'scan', panel: 'dead-letter' }));
  });
});

describe('appLinks codecs', () => {
  it('parseRunParam defaults empty/missing; accepts non-empty (never throws)', () => {
    expect(parseRunParam(null)).toBeNull();
    expect(parseRunParam(undefined)).toBeNull();
    expect(parseRunParam('')).toBeNull();
    expect(parseRunParam('   ')).toBeNull();
    expect(parseRunParam('run-1')).toBe('run-1');
    expect(parseRunParam('  run-1  ')).toBe('run-1');
  });

  it('serializeRunParam omits empty and round-trips with parse', () => {
    expect(serializeRunParam(null)).toBeNull();
    expect(serializeRunParam('')).toBeNull();
    expect(serializeRunParam('  ')).toBeNull();
    expect(serializeRunParam('run-9')).toBe('run-9');
    expect(parseRunParam(serializeRunParam('  x  '))).toBe('x');
  });




  it('builder + codec: run on history href parses back', () => {
    const { params } = parseHref(toDescriptionHistoryRun('batch-77'));
    expect(parseRunParam(params.get(APP_LINK_PARAMS.run))).toBe('batch-77');
  });

  // WBUX-5 Slice 1a — ?panes= codec [NAV-11]
  it('parsePanes defaults missing/malformed to both; accepts valid states', () => {
    expect(parsePanes(null)).toBe('both');
    expect(parsePanes(undefined)).toBe('both');
    expect(parsePanes('')).toBe('both');
    expect(parsePanes('nonsense')).toBe('both');
    expect(parsePanes(APP_LINK_VALUES.panesBoth)).toBe('both');
    expect(parsePanes(APP_LINK_VALUES.panesControlCollapsed)).toBe('control-collapsed');
    expect(parsePanes(APP_LINK_VALUES.panesLibraryCollapsed)).toBe('library-collapsed');
  });

  it('serializePanes omits both and round-trips collapsed states', () => {
    expect(serializePanes('both')).toBeNull();
    expect(serializePanes('control-collapsed')).toBe(APP_LINK_VALUES.panesControlCollapsed);
    expect(serializePanes('library-collapsed')).toBe(APP_LINK_VALUES.panesLibraryCollapsed);

    const states: PanesState[] = ['both', 'control-collapsed', 'library-collapsed'];
    for (const state of states) {
      const wire = serializePanes(state);
      expect(parsePanes(wire)).toBe(state);
    }
  });

  it('toWorkbench emits panes only for non-default collapsed states', () => {
    expect(toWorkbench({ panes: 'both' })).toBe('#/workbench');
    expect(toWorkbench({ panes: 'control-collapsed' })).toBe(
      '#/workbench?panes=control-collapsed',
    );
    expect(toWorkbench({ tab: 'scan', panel: 'conflicts', panes: 'library-collapsed' })).toBe(
      '#/workbench?tab=scan&panel=conflicts&panes=library-collapsed',
    );

    const { params } = parseHref(
      toWorkbench({ panel: 'conflicts', panes: 'control-collapsed' }),
    );
    expect(params.get(APP_LINK_PARAMS.panel)).toBe('conflicts');
    expect(params.get(APP_LINK_PARAMS.panes)).toBe('control-collapsed');
    expect(parsePanes(params.get(APP_LINK_PARAMS.panes))).toBe('control-collapsed');
  });
});
