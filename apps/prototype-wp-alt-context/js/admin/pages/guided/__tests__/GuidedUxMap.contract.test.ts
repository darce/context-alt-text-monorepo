import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

interface UxMapAction {
  id: string;
  [key: string]: unknown;
}

interface UxMapZone {
  id: string;
  label?: string;
  [key: string]: unknown;
}

interface UxMapScreen {
  id: string;
  kind?: string;
  title?: string;
  purpose?: string;
  action_states?: string[];
  zones?: UxMapZone[];
  [key: string]: unknown;
}

interface UxMapFlow {
  id: string;
  [key: string]: unknown;
}

interface UxMap {
  screens: UxMapScreen[];
  actions: UxMapAction[];
  flows: UxMapFlow[];
  open_questions?: string[];
  not_doing?: string[];
  [key: string]: unknown;
}

interface CopyCatalog {
  [key: string]: string;
}

interface TargetTestHook {
  test_id: string;
}

const MAP_PATH = resolve(__dirname, '../../../../../docs/ux-maps/guided-prototype.uxmap.json');
const COPY_PATH = resolve(
  __dirname,
  '../../../../../../../docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json',
);
const BRIEF_PATH = resolve(
  __dirname,
  '../../../../../../../docs/assessments/current/demo/altcontext_guided_demo_qm_v1/implementation-brief.json',
);

const STEP_SCREEN_IDS = ['context', 'names', 'draft', 'apply'] as const;
const REAL_NAMES = ['Justin Trudeau', 'Katy Perry'] as const;
const COPY_SAMPLE_KEYS = [
  'page.title',
  'step.context',
  'step.names',
  'step.draft',
  'step.apply',
  'live.request_unverified',
] as const;
const LIVE_ACTION_STATES = [
  'closed',
  'unavailable-unverified',
  'pending',
  'complete',
  'failed',
  'timed_out',
  'stopped',
  'no_result',
] as const;

const loadMap = (): UxMap => JSON.parse(readFileSync(MAP_PATH, 'utf8')) as UxMap;
const loadCopy = (): CopyCatalog => JSON.parse(readFileSync(COPY_PATH, 'utf8')) as CopyCatalog;
const loadHookIds = (): string[] => {
  const brief = JSON.parse(readFileSync(BRIEF_PATH, 'utf8')) as { target_test_hooks: TargetTestHook[] };
  return brief.target_test_hooks.map((hook) => hook.test_id);
};

const hookIdsFrom = (map: UxMap): string[] => {
  const wanted = new Set(loadHookIds());
  const found: string[] = [];
  for (const screen of map.screens) {
    if (wanted.has(screen.id)) {
      found.push(screen.id);
    }
    for (const zone of screen.zones ?? []) {
      if (wanted.has(zone.id)) {
        found.push(zone.id);
      }
    }
  }
  for (const action of map.actions) {
    if (wanted.has(action.id)) {
      found.push(action.id);
    }
  }
  return found;
};

describe('guided prototype ux-map contract (GUIDEDQM-1 shipped topology)', () => {
  it('would be wrong if the four step screens were missing or out of order context → names → draft → apply', () => {
    const map = loadMap();
    const stepIds = map.screens.map((screen) => screen.id).filter((id) => (STEP_SCREEN_IDS as readonly string[]).includes(id));
    expect(stepIds).toEqual([...STEP_SCREEN_IDS]);
  });

  it('would be wrong if the names screen omitted either fieldset test id or either shipped person name', () => {
    const map = loadMap();
    const names = map.screens.find((screen) => screen.id === 'names');
    expect(names, 'names screen missing').toBeDefined();
    const zoneIds = (names?.zones ?? []).map((zone) => zone.id);
    expect(zoneIds).toContain('name-choice-left');
    expect(zoneIds).toContain('name-choice-right');
    const namesCopy = JSON.stringify(names);
    for (const person of REAL_NAMES) {
      expect(namesCopy).toContain(person);
    }
    expect(namesCopy).not.toContain('Keanu');
    expect(namesCopy).not.toContain('Jordan Lee');
    expect(namesCopy).not.toContain('Rowan Ames');
  });

  it('would be wrong if any screen claimed identities were already matched or done before a visitor choice', () => {
    const map = loadMap();
    const screens = JSON.stringify(map.screens);
    expect(screens).not.toMatch(/you confirmed/i);
    expect(screens).not.toMatch(/match strength/i);
    expect(screens).not.toMatch(/matched to (justin|katy|jordan|rowan)/i);
    expect(screens).not.toMatch(/identities are (matched|done)/i);
    expect(screens).not.toMatch(/\bKeanu\b/);
  });

  it('would be wrong if the live disclosure were not the last screen, not closed by default, or missing the shipped recovery states', () => {
    const map = loadMap();
    expect(map.screens.at(-1)?.id).toBe('live');
    const live = map.screens.at(-1);
    expect(JSON.stringify(live)).toMatch(/closed by default/i);
    expect(live?.action_states?.[0]).toBe('closed');
    for (const state of LIVE_ACTION_STATES) {
      expect(live?.action_states, `missing live action_state ${state}`).toContain(state);
    }
  });

  it('would be wrong if the one-named flow or the both-omitted flow were missing', () => {
    const map = loadMap();
    const flowIds = map.flows.map((flow) => flow.id);
    expect(flowIds).toContain('one-named');
    expect(flowIds).toContain('both-omitted');
    expect(flowIds).toContain('core-walkthrough');
    expect(flowIds).toContain('fixture-missing');
    expect(flowIds).toContain('draft-survives-choice-change');
    expect(flowIds).toContain('repeated-apply-undo');
    expect(flowIds).toContain('live-failure-does-not-block-core');
  });

  it('would be wrong if InsightFace or the 2026-09-06 saved run appeared in screen copy instead of notes', () => {
    const map = loadMap();
    const screenCopy = JSON.stringify(map.screens);
    expect(screenCopy).not.toMatch(/insightface|buffalo/i);
    const notes = JSON.stringify({
      open_questions: map.open_questions ?? [],
      not_doing: map.not_doing ?? [],
    });
    expect(notes).toMatch(/insightface/i);
    expect(notes).toContain('2026-09-06');
  });

  it('would be wrong if any implementation-brief target_test_hooks id were missing, duplicated, or stored as something other than a hook id', () => {
    const map = loadMap();
    const expected = loadHookIds();
    const found = hookIdsFrom(map);
    expect([...found].sort()).toEqual([...expected].sort());
    expect(new Set(found).size, `duplicate hook ids: ${found.join(', ')}`).toBe(found.length);
  });

  it('would be wrong if page.title, the four step titles, or live.request_unverified were missing or invented', () => {
    const map = loadMap();
    const copy = loadCopy();
    const serialized = JSON.stringify(map);
    for (const key of COPY_SAMPLE_KEYS) {
      expect(copy[key], `copy catalog missing ${key}`).toEqual(expect.any(String));
      expect(serialized, `map is missing catalog string ${key}`).toContain(copy[key]);
    }
    expect(map.screens.find((screen) => screen.id === 'entry')?.title).toBe(copy['page.title']);
    expect(map.screens.find((screen) => screen.id === 'context')?.title).toBe(copy['step.context']);
    expect(map.screens.find((screen) => screen.id === 'names')?.title).toBe(copy['step.names']);
    expect(map.screens.find((screen) => screen.id === 'draft')?.title).toBe(copy['step.draft']);
    expect(map.screens.find((screen) => screen.id === 'apply')?.title).toBe(copy['step.apply']);
  });
});
