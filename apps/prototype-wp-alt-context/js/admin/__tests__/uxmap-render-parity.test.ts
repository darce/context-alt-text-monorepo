/**
 * UX-map render parity: owned *.uxmap.json labels must appear verbatim in the
 * sibling *.md, and labels the JSON has since renamed must not linger in the md.
 *
 * Scoped to roster-people and workbench-operator-loop — the two maps this lane
 * owns. A repo-wide sweep would go red on workbench-2pane.md (other-lane IA)
 * and on workbench-operator-loop.uxmap.md (starter inventory, not the render).
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const uxMapsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/ux-maps');

const OWNED_MAPS = ['roster-people', 'workbench-operator-loop'] as const;

/** Operator-facing labels renamed or deleted from the JSON; must not remain in the md. */
const RETIRED_LABELS = [
  'Person identity header',
  'Linked identities / faces',
  'Face-group drawer host (other)',
  'Face-group drawer (shim)',
  'Name control',
] as const;

type UxMapZone = {
  id: string;
  label: string;
};

type UxMapScreen = {
  id: string;
  title: string;
  zones?: UxMapZone[];
};

type UxMapDoc = {
  screens: UxMapScreen[];
};

const loadOwnedMap = (mapRef: (typeof OWNED_MAPS)[number]): { json: UxMapDoc; md: string; mdName: string } => {
  const jsonPath = path.join(uxMapsDir, `${mapRef}.uxmap.json`);
  const mdPath = path.join(uxMapsDir, `${mapRef}.md`);
  return {
    json: JSON.parse(readFileSync(jsonPath, 'utf8')) as UxMapDoc,
    md: readFileSync(mdPath, 'utf8'),
    mdName: `${mapRef}.md`,
  };
};

describe('ux-map render parity (owned maps)', () => {
  it('every json screen and zone label appears verbatim in the sibling md, and renamed labels do not linger', () => {
    for (const mapRef of OWNED_MAPS) {
      const { json, md, mdName } = loadOwnedMap(mapRef);
      const jsonLabels = new Set<string>();

      for (const screen of json.screens) {
        jsonLabels.add(screen.title);
        expect(
          md.includes(screen.title),
          `screen ${screen.id} title "${screen.title}" missing from ${mdName}`,
        ).toBe(true);

        for (const zone of screen.zones ?? []) {
          jsonLabels.add(zone.label);
          expect(
            md.includes(zone.label),
            `zone ${zone.id} label "${zone.label}" missing from ${mdName}`,
          ).toBe(true);
        }
      }

      for (const stale of RETIRED_LABELS) {
        if (jsonLabels.has(stale)) {
          continue;
        }
        expect(
          md.includes(stale),
          `renamed/retired label "${stale}" still appears in ${mdName}`,
        ).toBe(false);
      }
    }
  });
});
