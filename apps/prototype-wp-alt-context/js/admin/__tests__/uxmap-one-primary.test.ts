/**
 * D-22 / NAV-01: each ux-map screen lists at most one primary action.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const mapsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/ux-maps');
const OWNED_MAPS = ['roster-people', 'workbench-2pane', 'workbench-operator-loop', 'dashboard'] as const;

interface UxAction {
  id: string;
  hierarchy: string;
  screen_id?: string | null;
}

interface UxScreen {
  id: string;
  kind?: string;
  primary_action_id?: string | null;
}

interface UxMap {
  screens: UxScreen[];
  actions: UxAction[];
}

describe('D-22 one primary action per ux-map screen', () => {
  it.each(OWNED_MAPS)('%s screens have exactly one primary action matching primary_action_id', (mapRef) => {
    const json = JSON.parse(readFileSync(path.join(mapsDir, `${mapRef}.uxmap.json`), 'utf8')) as UxMap;
    expect(json.screens.length).toBeGreaterThan(0);

    for (const screen of json.screens) {
      if (screen.kind === 'exit') {
        continue;
      }
      const primaries = json.actions.filter(
        (action) => action.screen_id === screen.id && action.hierarchy === 'primary',
      );
      expect(
        primaries,
        `${mapRef} ${screen.id} primaries: ${primaries.map((action) => action.id).join(',')}`,
      ).toHaveLength(1);
      expect(screen.primary_action_id, `${mapRef} ${screen.id} missing primary_action_id`).toBe(
        primaries[0]?.id,
      );
    }
  });
});
