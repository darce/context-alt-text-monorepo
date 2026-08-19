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
  states?: string[];
}

interface UxScreen {
  id: string;
  zones?: UxZone[];
}

interface UxAction {
  id: string;
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
});
