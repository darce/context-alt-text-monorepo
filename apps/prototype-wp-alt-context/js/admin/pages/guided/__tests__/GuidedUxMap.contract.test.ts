import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

interface UxMapAction {
  id: string;
  [key: string]: unknown;
}
interface UxMapScreen {
  id: string;
  [key: string]: unknown;
}
interface UxMap {
  screens: UxMapScreen[];
  actions: UxMapAction[];
  [key: string]: unknown;
}

const MAP_PATH = resolve(__dirname, '../../../../../docs/ux-maps/guided-prototype.uxmap.json');

const loadMap = (): UxMap => JSON.parse(readFileSync(MAP_PATH, 'utf8')) as UxMap;

describe('guided prototype ux-map contract (GPFACE-1 wave 2)', () => {
  it('has a faces screen between the photo and the description that names both people', () => {
    const map = loadMap();
    const ids = map.screens.map((screen) => screen.id);
    expect(ids).toContain('face');
    const face = JSON.stringify(map.screens.find((screen) => screen.id === 'face'));
    expect(face).toContain('Faces found in the photo');
    expect(face).toContain('Face on the left');
    expect(face).toContain('Face on the right');
    expect(face).toContain('Katy Perry');
    expect(face).toContain('Justin Trudeau');
    expect(face).not.toContain('Keanu');
  });

  it('has one confirm action and one keep-unnamed action per person', () => {
    const map = loadMap();
    for (const person of ['katy-perry', 'justin-trudeau']) {
      expect(map.actions.find((action) => action.id === `confirm-${person}`)).toBeDefined();
      expect(map.actions.find((action) => action.id === `unnamed-${person}`)).toBeDefined();
    }
    expect(JSON.stringify(map.actions)).not.toContain('Keanu');
  });

  it('records the recognition engine and the saved-run provenance in notes, not in screen copy', () => {
    const map = loadMap();
    const screenCopy = JSON.stringify(map.screens);
    expect(screenCopy).not.toMatch(/insightface|buffalo/i);
    const rest = JSON.stringify({ ...map, screens: [] });
    expect(rest).toMatch(/insightface/i);
    expect(rest).toContain('2026-09-06');
  });

  it('has a flow where one person is named and the other is kept unnamed', () => {
    const map = loadMap();
    const flows = map.flows as { id: string }[];
    expect(flows.map((flow) => flow.id)).toContain('one-named');
  });
});
