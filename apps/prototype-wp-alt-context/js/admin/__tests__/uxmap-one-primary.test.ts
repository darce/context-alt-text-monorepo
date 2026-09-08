/**
 * D-22 / NAV-01: each ux-map screen lists at most one primary action.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const mapsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/ux-maps');
const OWNED_MAPS = [
  'roster-people',
  'workbench-2pane',
  'workbench-operator-loop',
  'dashboard',
  'describe-gpu-tier',
] as const;

/**
 * WBUX6-W3-L3-02: "exactly one primary per screen" forced a code-parity lie. The 2-pane
 * shell is a layout host — each pane owns its own primary — so it was given a fabricated
 * `act-scan-media-queue` primary purely to satisfy this gate; the toast overlay was given
 * a `dismiss-toast` primary that is declared `tertiary`. NAV-01/INT-05 constrain screens
 * that ask the operator to commit, not hosts and notifications that ask for nothing.
 *
 * The exemption stays fail-closed in both directions: a listed screen must own zero
 * primary-hierarchy actions and declare `primary_action_id: null`, and a screen that owns
 * zero primaries must be listed. A stale entry (screen renamed or deleted) also fails.
 */
const NO_PRIMARY_SCREENS: Record<string, string> = {
  'workbench-2pane:workbench-2pane-shell':
    'Layout host: it renders the control and library panes, each of which owns its own primary; the shell asks the operator to commit to nothing.',
  'describe-gpu-tier:toast-gpu-transition':
    'Transient notification: its only control is a tertiary Dismiss; a toast that claims a primary would compete with the screen underneath it (COG-03).',
};

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

const loadMap = (mapRef: string): UxMap =>
  JSON.parse(readFileSync(path.join(mapsDir, `${mapRef}.uxmap.json`), 'utf8')) as UxMap;

describe('D-22 one primary action per ux-map screen', () => {
  it.each(OWNED_MAPS)('%s screens have exactly one primary action matching primary_action_id', (mapRef) => {
    const json = loadMap(mapRef);
    expect(json.screens.length).toBeGreaterThan(0);

    for (const screen of json.screens) {
      if (screen.kind === 'exit') {
        continue;
      }
      const primaries = json.actions.filter(
        (action) => action.screen_id === screen.id && action.hierarchy === 'primary',
      );
      const exemptionKey = `${mapRef}:${screen.id}`;
      const exemption = NO_PRIMARY_SCREENS[exemptionKey];

      if (exemption !== undefined) {
        expect(
          primaries.map((action) => action.id),
          `${exemptionKey} is listed as owning no primary but declares one — remove the exemption or the action`,
        ).toEqual([]);
        expect(
          screen.primary_action_id,
          `${exemptionKey} owns no primary action, so primary_action_id must be null`,
        ).toBeNull();
        continue;
      }

      expect(
        primaries,
        `${mapRef} ${screen.id} primaries: ${primaries.map((action) => action.id).join(',')} — a screen with no primary must be listed in NO_PRIMARY_SCREENS with a rationale`,
      ).toHaveLength(1);
      expect(screen.primary_action_id, `${mapRef} ${screen.id} missing primary_action_id`).toBe(primaries[0]?.id);
    }
  });

  it('every NO_PRIMARY_SCREENS entry names a real screen and carries a rationale', () => {
    const unresolved: string[] = [];
    for (const [key, rationale] of Object.entries(NO_PRIMARY_SCREENS)) {
      const [mapRef, screenId] = key.split(':');
      expect(OWNED_MAPS, `${key} names a map that is not owned`).toContain(mapRef);
      if (!loadMap(mapRef).screens.some((screen) => screen.id === screenId)) {
        unresolved.push(key);
      }
      expect(rationale.length, `${key} exemption has no written rationale`).toBeGreaterThan(40);
    }
    expect(unresolved, `stale NO_PRIMARY_SCREENS entries: ${unresolved.join(', ')}`).toEqual([]);
  });
});
