/**
 * UX map JSON ↔ sibling Markdown render parity (UXW2-3-R3-23 / R3-24).
 * Lives under js/ so vitest include globs pick it up; it loads docs/ux-maps.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));
const mapsDir = path.resolve(here, '../../../docs/ux-maps');

interface UxZone {
  id: string;
  label?: string;
  states?: string[];
}

interface UxScreen {
  id: string;
  zones?: UxZone[];
}

interface UxAction {
  id: string;
  verb?: string;
  target?: string;
  hierarchy?: string;
  screen_id?: string | null;
}

interface UxMap {
  screens?: UxScreen[];
  actions?: UxAction[];
}

const loadPair = (stem: string): { json: UxMap; render: string } => {
  const json = JSON.parse(readFileSync(path.join(mapsDir, `${stem}.uxmap.json`), 'utf8')) as UxMap;
  const render = readFileSync(path.join(mapsDir, `${stem}.md`), 'utf8');
  return { json, render };
};

describe('ux-map render parity (UXW2-3-R3-23)', () => {
  it('gpu-operator-control render documents every zone, state, and action id', () => {
    const { json, render } = loadPair('gpu-operator-control');
    const missing: string[] = [];

    for (const screen of json.screens ?? []) {
      for (const zone of screen.zones ?? []) {
        if (!render.includes(zone.id)) {
          missing.push(`zone ${zone.id}`);
        }
        for (const state of zone.states ?? []) {
          if (!render.includes(state)) {
            missing.push(`expected ux-map render to document state '${state}' (zone ${zone.id})`);
          }
        }
      }
    }
    for (const action of json.actions ?? []) {
      if (!render.includes(action.id)) {
        missing.push(`action ${action.id}`);
      }
    }

    expect(missing, missing.join('; ')).toEqual([]);
  });

  it('workbench-2pane render documents every zone id, state, and action id', () => {
    const { json, render } = loadPair('workbench-2pane');
    const missing: string[] = [];

    for (const screen of json.screens ?? []) {
      for (const zone of screen.zones ?? []) {
        if (!render.includes(zone.id)) {
          missing.push(`zone ${zone.id}`);
        }
        for (const state of zone.states ?? []) {
          if (!render.includes(state)) {
            missing.push(`expected ux-map render to document state '${state}' (zone ${zone.id})`);
          }
        }
      }
    }
    for (const action of json.actions ?? []) {
      if (!render.includes(action.id)) {
        missing.push(`action ${action.id}`);
      }
    }

    expect(missing, missing.join('; ')).toEqual([]);
  });

  it('public-demo-describe render documents every zone, state, and action id', () => {
    const { json, render } = loadPair('public-demo-describe');
    const missing: string[] = [];

    for (const screen of json.screens ?? []) {
      for (const zone of screen.zones ?? []) {
        if (!render.includes(zone.id)) {
          missing.push(`zone ${zone.id}`);
        }
        for (const state of zone.states ?? []) {
          if (!render.includes(state)) {
            missing.push(`expected ux-map render to document state '${state}' (zone ${zone.id})`);
          }
        }
      }
    }
    for (const action of json.actions ?? []) {
      if (!render.includes(action.id)) {
        missing.push(`action ${action.id}`);
      }
    }

    expect(missing, missing.join('; ')).toEqual([]);
  });

  /**
   * WBUX-6-r0902w2-S1R1-F1: `uxmap-one-primary.test.ts` only checks one primary
   * *per screen_id*, so the SSOT could keep two competing job verbs — a footer
   * `Describe` and a separate `Scan media queue` / `Analyze selected` — without
   * any gate going red. This asserts the footer contract itself: the library
   * pane owns exactly one job-pipeline CTA, and the retired scan verb does not
   * claim a second one (INT-05 one job entry, COG-03 one decision).
   */
  it('workbench-library owns exactly one job-pipeline CTA and no competing scan verb', () => {
    const { json } = loadPair('workbench-2pane');
    const actions = json.actions ?? [];

    const libraryJobCtas = actions.filter(
      (action) => action.screen_id === 'workbench-library' && action.target === 'job-pipeline',
    );
    expect(
      libraryJobCtas.map((action) => action.id),
      'workbench-library must expose exactly one job-pipeline CTA',
    ).toEqual(['act-bulk-describe']);
    expect(libraryJobCtas[0]?.hierarchy).toBe('primary');
    expect(libraryJobCtas[0]?.verb).toMatch(/^Describe N selected\b/);

    const footer = (json.screens ?? [])
      .find((screen) => screen.id === 'workbench-library')
      ?.zones?.find((zone) => zone.id === 'z-lib-actions');
    expect(footer, 'workbench-library missing z-lib-actions footer zone').toBeDefined();
    const footerLabel = footer?.label ?? '';
    expect(footerLabel).toMatch(/ONE job CTA/);
    expect(footerLabel, 'footer must not advertise a second scan/analyze CTA').not.toMatch(
      /\bscan CTAs?\b|\bBulk describe \/ scan\b/i,
    );

    // The scan survives only as a phase of the Describe primary, never as its own
    // library-footer control.
    const scan = actions.find((action) => action.id === 'act-scan-media-queue');
    if (scan) {
      expect(scan.screen_id, 'act-scan-media-queue must not claim the library footer').not.toBe('workbench-library');
      expect(scan.verb).toMatch(/no separate scan control/);
    }
  });
});
