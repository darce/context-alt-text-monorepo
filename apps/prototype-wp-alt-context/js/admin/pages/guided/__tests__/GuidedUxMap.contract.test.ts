import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

type UxMapAction = { id: string; [key: string]: unknown };
type UxMapScreen = { id: string; [key: string]: unknown };
type UxMap = { screens: UxMapScreen[]; actions: UxMapAction[]; [key: string]: unknown };

const MAP_PATH = resolve(__dirname, '../../../../../docs/ux-maps/guided-prototype.uxmap.json');

const loadMap = (): UxMap => JSON.parse(readFileSync(MAP_PATH, 'utf8')) as UxMap;

describe('guided prototype ux-map contract (GPFACE-1)', () => {
  it('has a face-match screen between the photo and the description', () => {
    const map = loadMap();
    const ids = map.screens.map((screen) => screen.id);
    expect(ids).toContain('face');
    expect(JSON.stringify(map.screens.find((screen) => screen.id === 'face'))).toContain('Face found in the photo');
  });

  it('names the matched person in the confirm action', () => {
    const map = loadMap();
    const confirm = map.actions.find((action) => action.id === 'confirm');
    expect(confirm).toBeDefined();
    expect(JSON.stringify(confirm)).toContain('Keanu');
  });

  it('records the recognition engine once in plain-language notes, not in screen copy', () => {
    const map = loadMap();
    const screenCopy = JSON.stringify(map.screens);
    expect(screenCopy).not.toMatch(/insightface/i);
    const rest = JSON.stringify({ ...map, screens: [] });
    expect(rest).toMatch(/insightface/i);
  });
});
