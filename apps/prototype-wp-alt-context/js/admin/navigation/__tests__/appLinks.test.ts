import { describe, expect, it } from 'vitest';

import {
  APP_LINK_PARAMS,
  APP_LINK_VALUES,
  SCAN_CONFLICTS_HREF,
  SCAN_DEAD_LETTER_HREF,
  buildWorkbenchOverlayHref,
  parseMediaExpanded,
  parseRunParam,
  serializeMediaExpanded,
  serializeRunParam,
  toDashboard,
  toDescriptionHistory,
  toDescriptionHistoryRun,
  toRetention,
  toRoster,
  toRosterPerson,
  toWorkbench,
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
    expect(toWorkbench({ media: 'expanded' })).toBe('#/workbench?media=expanded');
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
      media: 'expanded',
    });
    const { path, params } = parseHref(href);
    expect(path).toBe('/workbench');
    expect(params.get(APP_LINK_PARAMS.tab)).toBe('scan');
    expect(params.get(APP_LINK_PARAMS.panel)).toBe('dead-letter');
    expect(params.get(APP_LINK_PARAMS.advanced)).toBe(APP_LINK_VALUES.advancedOpen);
    expect(params.get(APP_LINK_PARAMS.status)).toBe('missing');
    expect(params.get(APP_LINK_PARAMS.media)).toBe(APP_LINK_VALUES.mediaExpanded);
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

  it('parseMediaExpanded only treats expanded as true; never throws', () => {
    expect(parseMediaExpanded(null)).toBe(false);
    expect(parseMediaExpanded(undefined)).toBe(false);
    expect(parseMediaExpanded('')).toBe(false);
    expect(parseMediaExpanded('collapsed')).toBe(false);
    expect(parseMediaExpanded('yes')).toBe(false);
    expect(parseMediaExpanded(APP_LINK_VALUES.mediaExpanded)).toBe(true);
  });

  it('serializeMediaExpanded omits collapsed and round-trips expanded', () => {
    expect(serializeMediaExpanded(false)).toBeNull();
    expect(serializeMediaExpanded(true)).toBe(APP_LINK_VALUES.mediaExpanded);
    expect(parseMediaExpanded(serializeMediaExpanded(true))).toBe(true);
    expect(parseMediaExpanded(serializeMediaExpanded(false))).toBe(false);
  });

  it('builder + codec: media=expanded on workbench href parses true', () => {
    const { params } = parseHref(toWorkbench({ media: 'expanded' }));
    expect(parseMediaExpanded(params.get(APP_LINK_PARAMS.media))).toBe(true);
  });

  it('builder + codec: run on history href parses back', () => {
    const { params } = parseHref(toDescriptionHistoryRun('batch-77'));
    expect(parseRunParam(params.get(APP_LINK_PARAMS.run))).toBe('batch-77');
  });
});
