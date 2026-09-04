/**
 * UX-map SSOT guard for every map under docs/ux-maps/. Two layers:
 *
 *  1. **Schema conformance** — every owned `*.uxmap.json` must validate against the
 *     canonical `UxMap` model (`workbay_canvas_mcp/ux_map/models.py`), mirrored here
 *     in TypeScript so the guard runs in-process with no Python dependency.
 *  2. **Render parity** — the semantic Markdown projection is parsed and deep-compared
 *     with every owned JSON map; focused reverse-direction guards reject stale ids.
 *
 * DEMO-UX-1-D-15: `loadOwnedMap` used to do `JSON.parse(...) as UxMapDoc` — a
 * compile-time cast with zero runtime checking — so the parity guard stayed green
 * while every committed SSOT was structurally unloadable by the Python renderer that
 * owns the schema (DRIFT-03: an SSOT that cannot be loaded has stopped being a source
 * of truth). The cast is now a validated parse.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { parseRenderedUxMap, projectUxMapForRenderParity, type UxMapRenderSource } from '../uxmap/renderParity';

const uxMapsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/ux-maps');
const enumSnapshotPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures/uxmap-enums.snapshot.json',
);

const OWNED_MAPS = [
  'roster-people',
  'workbench-2pane',
  'workbench-operator-loop',
  'dashboard',
  'describe-gpu-tier',
  'febt-1-job-error-states',
] as const;

/**
 * WBUX6-W3-L3-01: `describe-gpu-tier` arrived with the GPUUX-1 merge and was absent from
 * both `OWNED_MAPS` lists, so an entire SSOT was ungated — a fail-open ownership list is
 * the coverage-gaming failure mode of TEST-11, and the gate below is the upward ratchet
 * (OBS-11) that stops the list sliding back down.
 */
const REQUIRED_OWNED_MAPS = ['dashboard', 'describe-gpu-tier', 'workbench-2pane', 'febt-1-job-error-states'] as const;

/**
 * Maps that exist on disk but cannot be enrolled in OWNED_MAPS yet, each with the reason and
 * the owner who must promote it. This is the named-exemption form of the ownership ratchet,
 * not an escape hatch: the on-disk gate below still fails for any map that is neither owned
 * nor listed here, a listed map whose file is gone fails, and a listed map that has since
 * become schema-conformant fails until it is promoted into OWNED_MAPS. So the list can only
 * shrink, never silently absorb the next unenrolled SSOT.
 */
const QUARANTINED_MAPS: Record<string, string> = {};

/** Operator-facing labels renamed or deleted from the JSON; must not remain in the md. */
const RETIRED_LABELS = [
  'Person identity header',
  'Linked identities / faces',
  'Face-group drawer host (other)',
  'Face-group drawer (shim)',
  'Name control',
] as const;

/* ------------------------------------------------------------------ *
 * Canonical enums — mirrored verbatim from ux_map/models.py.
 * Adding a member here without adding it upstream re-opens the drift.
 * ------------------------------------------------------------------ */

const MAP_STATES = ['default', 'loading', 'empty', 'error', 'offline', 'first_time', 'edge_input', 'degraded'] as const;

const ZONE_ROLES = ['content', 'nav', 'status', 'queue', 'job', 'ai_review', 'forced_choice', 'form', 'other'] as const;

const SCREEN_KINDS = ['screen', 'overlay', 'exit'] as const;

const ACTION_HIERARCHIES = ['primary', 'secondary', 'tertiary', 'destructive'] as const;

/* ------------------------------------------------------------------ *
 * Strict model specs (pydantic `extra="forbid"` semantics).
 * ------------------------------------------------------------------ */

interface ModelSpec {
  name: string;
  fields: Record<string, FieldSpec>;
}

type FieldSpec =
  | { kind: 'str'; required?: boolean; nullable?: boolean }
  | { kind: 'bool'; required?: boolean }
  | { kind: 'int'; required?: boolean; nullable?: boolean }
  | { kind: 'enum'; values: readonly string[]; required?: boolean; nullable?: boolean }
  | { kind: 'strList'; required?: boolean }
  | { kind: 'enumList'; values: readonly string[] }
  | { kind: 'modelList'; model: () => ModelSpec };

const JOB_MODEL: ModelSpec = {
  name: 'Job',
  fields: {
    id: { kind: 'str', required: true },
    label: { kind: 'str', required: true },
  },
};

const ZONE_MODEL: ModelSpec = {
  name: 'Zone',
  fields: {
    id: { kind: 'str', required: true },
    label: { kind: 'str', required: true },
    role: { kind: 'enum', values: ZONE_ROLES, required: true },
    evidence_linked: { kind: 'bool' },
    max_candidates: { kind: 'int', nullable: true },
    states: { kind: 'enumList', values: MAP_STATES },
  },
};

const SCREEN_MODEL: ModelSpec = {
  name: 'Screen',
  fields: {
    id: { kind: 'str', required: true },
    kind: { kind: 'enum', values: SCREEN_KINDS, required: true },
    title: { kind: 'str', required: true },
    purpose: { kind: 'str', required: true },
    route: { kind: 'str', required: true },
    wp_page: { kind: 'str', nullable: true },
    job_entry: { kind: 'bool' },
    deep_link: { kind: 'bool' },
    url_params: { kind: 'strList' },
    zones: { kind: 'modelList', model: () => ZONE_MODEL },
    states: { kind: 'enumList', values: MAP_STATES },
    primary_action_id: { kind: 'str', nullable: true },
    code_ref: { kind: 'str', nullable: true },
  },
};

const FLOW_STEP_MODEL: ModelSpec = {
  name: 'FlowStep',
  fields: {
    screen_id: { kind: 'str', required: true },
    branch_label: { kind: 'str', nullable: true },
  },
};

const FLOW_MODEL: ModelSpec = {
  name: 'Flow',
  fields: {
    id: { kind: 'str', required: true },
    job: { kind: 'str', required: true },
    steps: { kind: 'modelList', model: () => FLOW_STEP_MODEL },
    label: { kind: 'str', nullable: true },
  },
};

const ACTION_MODEL: ModelSpec = {
  name: 'Action',
  fields: {
    id: { kind: 'str', required: true },
    verb: { kind: 'str', required: true },
    target: { kind: 'str', required: true },
    hierarchy: { kind: 'enum', values: ACTION_HIERARCHIES, required: true },
    costly: { kind: 'bool' },
    irreversible: { kind: 'bool' },
    preview_required: { kind: 'bool' },
    screen_id: { kind: 'str', nullable: true },
  },
};

const DOMAIN_STATE_MAPPING_MODEL: ModelSpec = {
  // Local lossless-render extension. render_ux_maps.py removes this field before handing
  // the canonical portion to upstream Pydantic, then emits the typed table itself.
  name: 'DomainStateMapping',
  fields: {
    domain_states: { kind: 'strList', required: true },
    canonical_state: { kind: 'enum', values: MAP_STATES, required: true },
  },
};

const UX_MAP_MODEL: ModelSpec = {
  name: 'UxMap',
  fields: {
    map_ref: { kind: 'str', required: true },
    product: { kind: 'str', required: true },
    source_fixture: { kind: 'str', nullable: true },
    goals: { kind: 'strList' },
    jobs: { kind: 'modelList', model: () => JOB_MODEL },
    screens: { kind: 'modelList', model: () => SCREEN_MODEL },
    flows: { kind: 'modelList', model: () => FLOW_MODEL },
    actions: { kind: 'modelList', model: () => ACTION_MODEL },
    open_questions: { kind: 'strList' },
    not_doing: { kind: 'strList' },
    domain_state_mappings: { kind: 'modelList', model: () => DOMAIN_STATE_MAPPING_MODEL },
  },
};

/* ------------------------------------------------------------------ *
 * Validator
 * ------------------------------------------------------------------ */

interface Issue {
  loc: string;
  type: string;
  input: unknown;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const at = (loc: string, key: string | number): string => (loc === '' ? `${key}` : `${loc}.${key}`);

const preview = (input: unknown): string => {
  const raw = typeof input === 'string' ? input : JSON.stringify(input);
  return (raw ?? String(input)).slice(0, 80);
};

const validateScalar = (value: unknown, spec: FieldSpec, loc: string, issues: Issue[]): void => {
  switch (spec.kind) {
    case 'str':
      if (spec.nullable && value === null) {
        return;
      }
      if (typeof value !== 'string') {
        issues.push({ loc, type: 'string_type', input: value });
      }
      return;
    case 'bool':
      if (typeof value !== 'boolean') {
        issues.push({ loc, type: 'bool_type', input: value });
      }
      return;
    case 'int':
      if (spec.nullable && value === null) {
        return;
      }
      if (typeof value !== 'number' || !Number.isInteger(value)) {
        issues.push({ loc, type: 'int_type', input: value });
      }
      return;
    case 'enum':
      if (spec.nullable && value === null) {
        return;
      }
      if (typeof value !== 'string' || !spec.values.includes(value)) {
        issues.push({ loc, type: 'enum', input: value });
      }
      return;
    case 'strList':
      if (!Array.isArray(value)) {
        issues.push({ loc, type: 'list_type', input: value });
        return;
      }
      value.forEach((item, index) => {
        if (typeof item !== 'string') {
          issues.push({ loc: at(loc, index), type: 'string_type', input: item });
        }
      });
      return;
    case 'enumList':
      if (!Array.isArray(value)) {
        issues.push({ loc, type: 'list_type', input: value });
        return;
      }
      value.forEach((item, index) => {
        if (typeof item !== 'string' || !spec.values.includes(item)) {
          issues.push({ loc: at(loc, index), type: 'enum', input: item });
        }
      });
      return;
    case 'modelList':
      if (!Array.isArray(value)) {
        issues.push({ loc, type: 'list_type', input: value });
        return;
      }
      value.forEach((item, index) => {
        validateModel(item, spec.model(), at(loc, index), issues);
      });
  }
};

const validateModel = (value: unknown, spec: ModelSpec, loc: string, issues: Issue[]): void => {
  if (!isRecord(value)) {
    issues.push({ loc, type: 'model_type', input: value });
    return;
  }

  for (const key of Object.keys(value)) {
    if (!Object.hasOwn(spec.fields, key)) {
      issues.push({ loc: at(loc, key), type: 'extra_forbidden', input: value[key] });
    }
  }

  for (const [key, fieldSpec] of Object.entries(spec.fields)) {
    if (!(key in value)) {
      if ('required' in fieldSpec && fieldSpec.required) {
        issues.push({ loc: at(loc, key), type: 'missing', input: undefined });
      }
      continue;
    }
    validateScalar(value[key], fieldSpec, at(loc, key), issues);
  }
};

/** Mirrors the `_unique_*` model validators on Screen and UxMap. */
const validateUniqueness = (doc: unknown, issues: Issue[]): void => {
  if (!isRecord(doc)) {
    return;
  }

  const collect = (key: string): string[] => {
    const rows = doc[key];
    if (!Array.isArray(rows)) {
      return [];
    }
    return rows.filter(isRecord).map((row) => String(row.id));
  };

  for (const key of ['jobs', 'screens', 'flows', 'actions']) {
    const ids = collect(key);
    if (new Set(ids).size !== ids.length) {
      issues.push({ loc: key, type: 'duplicate_ids', input: ids });
    }
  }

  const screens = Array.isArray(doc.screens) ? doc.screens : [];
  screens.forEach((screen, index) => {
    if (!isRecord(screen) || !Array.isArray(screen.zones)) {
      return;
    }
    const ids = screen.zones.filter(isRecord).map((zone) => String(zone.id));
    if (new Set(ids).size !== ids.length) {
      issues.push({ loc: `screens.${index}.zones`, type: 'duplicate_zone_ids', input: ids });
    }
  });
};

const validateUxMap = (doc: unknown): Issue[] => {
  const issues: Issue[] = [];
  validateModel(doc, UX_MAP_MODEL, '', issues);
  validateUniqueness(doc, issues);
  return issues;
};

const formatIssues = (issues: Issue[]): string[] =>
  issues.map((issue) => `${issue.loc} | ${issue.type} | ${preview(issue.input)}`);

interface UxMapEnumSnapshot {
  mapStates: string[];
  zoneRoles: string[];
}

/* ------------------------------------------------------------------ *
 * Typed view of the parts the parity assertions read.
 * ------------------------------------------------------------------ */

interface UxMapZone {
  id: string;
  label: string;
  role: string;
  states?: string[];
}
interface UxMapScreen {
  id: string;
  title: string;
  purpose?: string;
  code_ref?: string | null;
  url_params?: string[];
  zones?: UxMapZone[];
}
interface UxMapAction {
  id: string;
  verb?: string;
}
interface UxMapDoc {
  screens: UxMapScreen[];
  actions?: UxMapAction[];
}

const readMapJson = (mapRef: string): unknown =>
  JSON.parse(readFileSync(path.join(uxMapsDir, `${mapRef}.uxmap.json`), 'utf8')) as unknown;

/** Validated parse — replaces the old unchecked `as UxMapDoc` cast. */
const loadOwnedMap = (mapRef: (typeof OWNED_MAPS)[number]): { json: UxMapDoc; md: string; mdName: string } => {
  const raw = readMapJson(mapRef);
  const issues = validateUxMap(raw);
  if (issues.length > 0) {
    throw new Error(
      `${mapRef}.uxmap.json fails canonical UxMap schema (${issues.length} errors):\n  ${formatIssues(issues).join('\n  ')}`,
    );
  }
  return {
    json: raw as UxMapDoc,
    md: readFileSync(path.join(uxMapsDir, `${mapRef}.md`), 'utf8'),
    mdName: `${mapRef}.md`,
  };
};

describe('ux-map SSOT schema conformance (owned maps)', () => {
  it('flags prototype-inherited field names as forbidden extras', () => {
    const issues: Issue[] = [];
    validateModel({ constructor: 'mutant' }, { name: 'Mutant', fields: {} }, '', issues);

    expect(formatIssues(issues)).toEqual(['constructor | extra_forbidden | mutant']);
  });

  it('keeps source paths out of operator-visible copy (WBUX6-W3-L3-06)', () => {
    // A repo path in a `label`/`verb`/`purpose` is not operator copy -- it is a code
    // pointer in the wrong field. It also silently couples the map to the retired-
    // vocabulary ban: `.../identity-clusters/Foo.tsx` tripped /\bclusters?\b/ on a
    // PATH SEGMENT, so a pure rename turned an unrelated test red. `code_ref` is the
    // sanctioned home (banned-vocabulary.test.tsx exempts it by name); the upstream
    // workbay_canvas_mcp Zone/Action models forbid extra keys, so until they carry a
    // code_ref of their own the only correct answer for a zone or action is to omit
    // the path, not to smuggle it into prose.
    const COPY_KEYS = new Set(['title', 'label', 'purpose', 'verb', 'goals', 'description', 'branch_label']);
    const EXEMPT_KEYS = new Set(['id', 'url_params', 'code_ref', 'open_questions', 'not_doing']);
    const SOURCE_PATH = /(?:apps|packages|scripts|infra)\/[\w./-]+\.(?:tsx?|php|py|scss|json|ya?ml|sh)\b/;
    const offenders: string[] = [];
    const sweep = (value: unknown, key: string | undefined, loc: string): void => {
      if (key && EXEMPT_KEYS.has(key)) {
        return;
      }
      if (typeof value === 'string') {
        const hit = key && COPY_KEYS.has(key) ? SOURCE_PATH.exec(value) : null;
        if (hit) {
          offenders.push(`${loc} -> ${hit[0]}`);
        }
        return;
      }
      if (Array.isArray(value)) {
        value.forEach((item, i) => sweep(item, key, `${loc}[${i}]`));
        return;
      }
      if (value && typeof value === 'object') {
        for (const [childKey, child] of Object.entries(value)) {
          sweep(child, childKey, `${loc}.${childKey}`);
        }
      }
    };
    for (const mapRef of OWNED_MAPS) {
      sweep(readMapJson(mapRef), undefined, mapRef);
    }
    expect(offenders, offenders.join('; ')).toEqual([]);
    // The sweep must be able to see a violation, or it passes vacuously.
    const canary: string[] = [];
    const saved = offenders.length;
    sweep({ label: 'x apps/prototype-wp-alt-context/js/admin/Foo.tsx' }, undefined, 'canary');
    canary.push(...offenders.slice(saved));
    expect(canary).toHaveLength(1);
  });

  it('resolves every owned map screen code_ref to a real file', () => {
    const repoRoot = path.resolve(uxMapsDir, '../../../..');
    const missing: string[] = [];
    const checked: string[] = [];
    const check = (owner: string, ref: string): void => {
      checked.push(ref);
      if (!existsSync(path.join(repoRoot, ref))) {
        missing.push(`${owner} -> ${ref}`);
      }
    };
    for (const mapRef of OWNED_MAPS) {
      const { json } = loadOwnedMap(mapRef);
      for (const screen of json.screens) {
        if (screen.code_ref) {
          check(`${mapRef} ${screen.id}`, screen.code_ref);
        }
      }
    }
    expect(missing, missing.join('; ')).toEqual([]);
    expect(checked.length, 'no code_ref resolved -- the sweep would pass vacuously').toBeGreaterThan(0);
  });

  it('resolves every owned map source_fixture to a real file', () => {
    const repoRoot = path.resolve(uxMapsDir, '../../../..');
    const missing: string[] = [];
    let checked = 0;
    for (const mapRef of OWNED_MAPS) {
      const raw = readMapJson(mapRef) as { source_fixture?: unknown };
      if (typeof raw.source_fixture !== 'string' || raw.source_fixture.length === 0) {
        missing.push(`${mapRef} -> absent source_fixture`);
        continue;
      }
      checked += 1;
      if (!existsSync(path.join(repoRoot, raw.source_fixture))) {
        missing.push(`${mapRef} -> ${raw.source_fixture}`);
      }
    }
    expect(missing, missing.join('; ')).toEqual([]);
    expect(checked, 'no source_fixture paths resolved -- the sweep would pass vacuously').toBeGreaterThan(0);
  });

  it('keeps every owned map json and sibling md on disk (fail-closed)', () => {
    expect(OWNED_MAPS.length, 'OWNED_MAPS emptied — ownership list would vacuously pass').toBeGreaterThan(0);
    for (const required of REQUIRED_OWNED_MAPS) {
      expect(OWNED_MAPS, `${required} dropped from OWNED_MAPS — an SSOT would go ungated`).toContain(required);
    }
    for (const mapRef of OWNED_MAPS) {
      expect(
        existsSync(path.join(uxMapsDir, `${mapRef}.uxmap.json`)),
        `${mapRef}.uxmap.json is missing — OWNED_MAPS cannot silently skip an absent SSOT`,
      ).toBe(true);
      expect(
        existsSync(path.join(uxMapsDir, `${mapRef}.md`)),
        `${mapRef}.md is missing — render parity cannot silently skip an absent sibling`,
      ).toBe(true);
    }
  });

  it('enrolls every *.uxmap.json on disk — ownership cannot be fail-open', () => {
    const onDisk = readdirSync(uxMapsDir)
      .filter((name) => name.endsWith('.uxmap.json'))
      .map((name) => name.slice(0, -'.uxmap.json'.length))
      .sort();
    expect(
      onDisk,
      'a *.uxmap.json exists that neither OWNED_MAPS gates nor QUARANTINED_MAPS names (or one of those lists names a map that is gone)',
    ).toEqual([...OWNED_MAPS, ...Object.keys(QUARANTINED_MAPS)].sort());
  });

  it('rejects shadow *.uxmap.md artifacts — each SSOT has one generated markdown owner', () => {
    const shadowArtifacts = readdirSync(uxMapsDir)
      .filter((name) => name.endsWith('.uxmap.md'))
      .sort();
    expect(
      shadowArtifacts,
      'a *.uxmap.md shadows the canonical generated <map_ref>.md sibling and is outside render-parity ownership',
    ).toEqual([]);
  });

  it('keeps every quarantine entry justified, non-owned, and still non-conformant', () => {
    expect(
      Object.keys(QUARANTINED_MAPS),
      'QUARANTINED_MAPS reached zero; sr-001 forbids growing the exemption list again',
    ).toEqual([]);
  });

  it('throws when an owned-style map json cannot be read (absent-file discrimination)', () => {
    expect(() => readMapJson('__absent-owned-map__')).toThrow(/ENOENT|no such file/i);
  });

  it('rejects malformed payloads that are not a UxMap object', () => {
    expect(formatIssues(validateUxMap(null)).length, 'null must fail schema').toBeGreaterThan(0);
    expect(formatIssues(validateUxMap([])).length, 'array must fail schema').toBeGreaterThan(0);
    expect(formatIssues(validateUxMap({ map_ref: 1 })).length, 'wrong field types must fail schema').toBeGreaterThan(0);
    expect(() => {
      JSON.parse('{');
    }, 'garbage json must not parse').toThrow();
  });

  it('keeps the checked-in Python enum snapshot available', () => {
    expect(existsSync(enumSnapshotPath)).toBe(true);
  });

  it('keeps the TypeScript enum mirrors equal to the Python enum snapshot', () => {
    const snapshot = JSON.parse(readFileSync(enumSnapshotPath, 'utf8')) as UxMapEnumSnapshot;

    expect(new Set(MAP_STATES)).toEqual(new Set(snapshot.mapStates));
    expect(new Set(ZONE_ROLES)).toEqual(new Set(snapshot.zoneRoles));
  });

  for (const mapRef of OWNED_MAPS) {
    it(`${mapRef}.uxmap.json validates against the canonical UxMap schema`, () => {
      const issues = validateUxMap(readMapJson(mapRef));
      expect(formatIssues(issues), `${mapRef}.uxmap.json: ${issues.length} schema errors`).toEqual([]);
    });
  }
});

describe('ux-map render parity (owned maps)', () => {
  it.each(OWNED_MAPS)('%s.md is structurally equal to its JSON render projection', (mapRef) => {
    const raw = readMapJson(mapRef) as UxMapRenderSource;
    const md = readFileSync(path.join(uxMapsDir, `${mapRef}.md`), 'utf8');

    expect(parseRenderedUxMap(md)).toEqual(projectUxMapForRenderParity(raw));
  });

  it('every json screen and zone label appears verbatim in the sibling md, and renamed labels do not linger', () => {
    for (const mapRef of OWNED_MAPS) {
      const { json, md, mdName } = loadOwnedMap(mapRef);
      const jsonLabels = new Set<string>();

      for (const screen of json.screens) {
        jsonLabels.add(screen.title);
        expect(md.includes(screen.title), `screen ${screen.id} title "${screen.title}" missing from ${mdName}`).toBe(
          true,
        );

        for (const zone of screen.zones ?? []) {
          jsonLabels.add(zone.label);
          expect(md.includes(zone.label), `zone ${zone.id} label "${zone.label}" missing from ${mdName}`).toBe(true);
        }
      }

      for (const stale of RETIRED_LABELS) {
        if (jsonLabels.has(stale)) {
          continue;
        }
        expect(md.includes(stale), `renamed/retired label "${stale}" still appears in ${mdName}`).toBe(false);
      }
    }
  });

  it('md url_params lines match json per screen, and retired pane query is gone', () => {
    for (const mapRef of OWNED_MAPS) {
      const { json, md, mdName } = loadOwnedMap(mapRef);
      const usesPanes = json.screens.some((screen) => (screen.url_params ?? []).includes('panes'));

      for (const screen of json.screens) {
        const params = screen.url_params ?? [];
        if (params.length === 0) {
          continue;
        }
        const expected = `url_params: ${params.map((param) => `\`${param}\``).join(', ')}`;
        expect(md.includes(expected), `${mapRef} ${screen.id} missing "${expected}" from ${mdName}`).toBe(true);
      }

      if (usesPanes) {
        expect(md, `${mdName} still documents retired url param pane`).not.toMatch(/url_params:.*`pane`/);
        expect(md, `${mdName} ASCII still uses ?pane=`).not.toMatch(/#\/workbench\?pane=/);
      }
    }
  });

  /**
   * Replaces the old single `z-name-curate states=[…]` ASCII assertion. That line existed
   * nowhere in the deterministic render — it was hand-typed into the fenced ASCII block, so
   * the gate was requiring the md to *diverge* from its own generator (REF-09: a derived
   * artifact that is hand-edited drifts silently). The zone-table row is what
   * `docs/ux-maps/render_ux_maps.py` actually emits, and asserting it for every zone of
   * every owned map is strictly more coverage than the one hand-typed line ever gave.
   */
  it('every owned-map zone table row carries the json role and states verbatim', () => {
    const missing: string[] = [];
    for (const mapRef of OWNED_MAPS) {
      const { json, md, mdName } = loadOwnedMap(mapRef);
      for (const screen of json.screens) {
        for (const zone of screen.zones ?? []) {
          const row = `| \`${zone.id}\` | ${zone.label.replaceAll('|', '\\|')} | ${zone.role} | ${(
            zone.states ?? []
          ).join(', ')} |`;
          if (!md.includes(row)) {
            missing.push(`${mdName} ${zone.id}: expected row\n    ${row}`);
          }
        }
      }
    }
    expect(missing, missing.join('\n  ')).toEqual([]);
  });

  /**
   * WBUX6-W3-L3-05 reverse direction. The json→md checks above cannot see an id the JSON
   * has *deleted* that still lingers in the render — exactly how `act-scan-media-queue`
   * survived its own removal. A silent stale id is the doc equivalent of RLSE-05: the
   * reader believes a control exists that the SSOT no longer defines.
   */
  it('no z-/act- id appears in an owned md that the sibling json does not define', () => {
    const stale: string[] = [];
    for (const mapRef of OWNED_MAPS) {
      const { json, md, mdName } = loadOwnedMap(mapRef);
      const known = new Set<string>();
      for (const screen of json.screens) {
        known.add(screen.id);
        for (const zone of screen.zones ?? []) {
          known.add(zone.id);
        }
      }
      for (const action of json.actions ?? []) {
        known.add(action.id);
      }
      for (const token of md.match(/\b(?:z|act)-[a-z0-9][a-z0-9-]*\b/g) ?? []) {
        if (!known.has(token)) {
          stale.push(`${mdName}: ${token}`);
        }
      }
    }
    expect([...new Set(stale)], stale.join('; ')).toEqual([]);
  });

  /** A bare `Foo.tsx` basename is unresolvable by construction (TEST-11). */
  it('cites source files by repo-relative path, never by bare basename', () => {
    const bare: string[] = [];
    for (const mapRef of OWNED_MAPS) {
      const { json } = loadOwnedMap(mapRef);
      const prose: string[] = [];
      for (const screen of json.screens) {
        prose.push(screen.title, screen.purpose ?? '');
        for (const zone of screen.zones ?? []) {
          prose.push(zone.label);
        }
      }
      for (const action of json.actions ?? []) {
        prose.push(action.verb ?? '');
      }
      for (const hit of prose.join('\n').match(/(?<![/\w.])[A-Za-z][A-Za-z0-9_]*\.tsx?\b/g) ?? []) {
        bare.push(`${mapRef}: ${hit}`);
      }
    }
    expect(
      [...new Set(bare)],
      `bare source-file basenames (write them as apps/…/File.tsx): ${bare.join('; ')}`,
    ).toEqual([]);
  });

  /**
   * WBUX6-W3-L3-03. `a1599b346` dropped the say/don't-say table from workbench-2pane.md
   * while `roster-people.md` kept it, so the two review surfaces stopped sharing one
   * controlled vocabulary (DATA-14: divergent copies of the same rule). Both operator
   * surfaces must carry it.
   */
  it.each(['workbench-2pane', 'roster-people'] as const)(
    '%s.md keeps the controlled say/dont-say vocabulary section',
    (mapRef) => {
      const md = readFileSync(path.join(uxMapsDir, `${mapRef}.md`), 'utf8');
      expect(md, `${mapRef}.md lost its "## Vocabulary (say / don't say)" section`).toMatch(
        /^## Vocabulary \(say \/ don't say\)$/m,
      );
      // Both surfaces must carry a real say/don't-say table, not just the heading. Column
      // order differs between the two maps, so match the header cells, not a fixed row.
      const section = md.split(/^## /m).find((chunk) => chunk.startsWith("Vocabulary (say / don't say)\n"));
      const header = (section ?? '').split('\n').find((line) => line.startsWith('| '));
      expect(header, `${mapRef}.md vocabulary section has no table`).toBeDefined();
      expect(header, `${mapRef}.md vocabulary table has no "Don't say" column`).toMatch(/\|\s*Don't say\s*\|/);
      expect(header, `${mapRef}.md vocabulary table has no "Say" column`).toMatch(/\|\s*Say\s*\|/);
      expect(
        (section ?? '').split('\n').filter((line) => line.startsWith('| ')).length,
        `${mapRef}.md vocabulary table has no entries`,
      ).toBeGreaterThan(2);
    },
  );

  it('keeps the typed domain-to-canonical state mapping exact and enum-backed', () => {
    const raw = readMapJson('workbench-operator-loop') as {
      domain_state_mappings?: Array<{ domain_states: string[]; canonical_state: string }>;
    };
    const mappings = raw.domain_state_mappings ?? [];
    expect(mappings).toEqual([
      { domain_states: ['unavailable'], canonical_state: 'offline' },
      { domain_states: ['repair', 'read_only'], canonical_state: 'degraded' },
      { domain_states: ['zero_evidence'], canonical_state: 'empty' },
      { domain_states: ['busy'], canonical_state: 'loading' },
      { domain_states: ['filtered', 'suggested_label'], canonical_state: 'default' },
      { domain_states: ['missing_image'], canonical_state: 'edge_input' },
    ]);
    expect(mappings.length, 'domain-state mapping disappeared').toBeGreaterThan(0);
    for (const mapping of mappings) {
      expect(MAP_STATES, `${mapping.canonical_state} is not in the canonical MapState enum`).toContain(
        mapping.canonical_state,
      );
    }
  });
});

/**
 * WBUX-6-r0902w2-S1R1-F1 + the post-merge MediaSelection footer contract. The SSOT must
 * encode the states the footer actually has: four aria-disabled holds (RLSE-04 every state
 * is designed; A11Y-21 the hold is announced, never HTML-disabled and therefore never
 * focus-stripped) plus `settings-unavailable`, which RELEASES the hold and degrades to
 * recognition-off rather than failing silently (RLSE-05).
 */
describe('workbench-library footer state contract (z-lib-actions)', () => {
  const footer = () => {
    const { json } = loadOwnedMap('workbench-2pane');
    const zone = json.screens
      .find((screen) => screen.id === 'workbench-library')
      ?.zones?.find((item) => item.id === 'z-lib-actions');
    expect(zone, 'workbench-2pane workbench-library is missing z-lib-actions').toBeDefined();
    // Narrowed by the `toBeDefined()` above, which vitest cannot express in the type
    // system; `@typescript-eslint/non-nullable-type-assertion-style` requires `!` here.
    return zone!;
  };

  it('declares every canonical state the four holds and the degraded fallback need', () => {
    expect(footer().states, 'z-lib-actions states must cover offline + zero-selection holds').toEqual([
      'default',
      'loading',
      'empty',
      'error',
      'offline',
      'degraded',
    ]);
  });

  it.each(['offline', 'zero-selection', 'identifying', 'settings-pending', 'settings-unavailable'])(
    'names the %s footer state in the zone label',
    (reason) => {
      expect(footer().label, `z-lib-actions label must name the ${reason} state`).toContain(reason);
    },
  );

  it('holds are aria-disabled with a reason id, never the HTML disabled attribute', () => {
    const label = footer().label;
    expect(label).toContain('aria-disabled="true"');
    expect(label).toContain('aria-describedby');
    expect(label, 'the footer must not claim the HTML disabled attribute').toMatch(/never the HTML disabled attribute/);
  });

  it('settings-unavailable releases the hold instead of adding a fifth one', () => {
    const label = footer().label;
    expect(label).toMatch(/Four hold reasons/);
    expect(label, 'settings-unavailable must be documented as hold-adjacent, not a hold').toMatch(
      /settings-unavailable is a fifth, hold-adjacent state and NOT a hold/,
    );
    expect(label, 'the released hold must say recognition falls back to off').toMatch(/hold is RELEASED/);
  });

  /**
   * Amendment from the workbench-CTA lane: the degraded disclosure has fixed copy and is
   * paired with an icon, never colour alone (sr-004).
   */
  it('pins the settings-unavailable disclosure copy and its non-colour cue', () => {
    const label = footer().label;
    expect(label, 'degraded disclosure copy is the contract, not an approximation').toContain(
      'Recognition settings unavailable — describing without identifying people · ~N credits',
    );
    expect(label, 'the degradation must carry an icon, not colour alone (sr-004)').toMatch(/AlertTriangle icon/);
  });

  /**
   * WBUX6-W4-B-02, routed to this lane: an `aria-describedby` target is only heard on
   * focus, so a degradation that appears while focus is elsewhere is silent. The SSOT
   * splits the two surfaces — one node to describe, a separate polite live region to
   * announce (A11Y-21) — rather than overloading one node with both duties.
   */
  it('splits the describedby target from the announcement surface for the degraded notice', () => {
    const label = footer().label;
    expect(label, 'the degraded notice needs its own live region').toMatch(/role="status" aria-live="polite"/);
    expect(label, 'the live region must not double as the describedby target').toMatch(/is not the describedby target/);
    expect(label).toMatch(/one surface to describe, one surface to announce/);
  });

  it('keeps one Cancel across identifying and describing, and no separate scan CTA', () => {
    const { json } = loadOwnedMap('workbench-2pane');
    expect(footer().label).toMatch(/single Cancel control spans the identifying and describing phases/);
    expect(
      (json.actions ?? []).map((action) => action.id),
      'act-scan-media-queue is deleted — Describe owns the scan trigger',
    ).not.toContain('act-scan-media-queue');
  });

  /**
   * Amendment: the single Cancel control's visible label is state-dependent. Pinning one
   * literal string here would have made the SSOT stale the moment the phase changed, so the
   * map encodes a state -> label mapping (RLSE-04: every state is designed).
   */
  it.each([
    ['identifying', 'Cancel people identification'],
    ['describing', 'Cancel describe run'],
    ['in-flight cancel', 'Cancelling…'],
  ])('maps the %s phase to the Cancel label %s', (_phase, expected) => {
    expect(footer().label, `the Cancel state->label mapping is missing "${expected}"`).toContain(expected);
  });

  it('describes Cancel as one state-dependent control, not a fixed string', () => {
    const label = footer().label;
    expect(label, 'a single literal Cancel label would be a stale pin').toMatch(
      /visible label is state-dependent, not a fixed string/,
    );
    expect(label, 'exactly one Cancel control may be rendered at a time').toMatch(
      /exactly one control matching \/\^Cancel \/ is rendered at a time/,
    );
  });
});

/* ------------------------------------------------------------------ *
 * Generator provenance: the `.md` is a derived artifact and
 * `docs/ux-maps/render_ux_maps.py` is its only sanctioned writer
 * (DATA-14 one authority owns the record; REF-09 a hand-edited derived
 * artifact drifts silently). The parser-backed projection above asserts
 * semantic render fidelity in process; these guards additionally pin the
 * sections a regeneration must emit and the hand-authored prose it must
 * carry across (`KEEP_SECTIONS`).
 * ------------------------------------------------------------------ */

const rendererPath = path.join(uxMapsDir, 'render_ux_maps.py');

const sectionRows = (markdown: string, heading: string): number => {
  const start = markdown.indexOf(heading);
  if (start < 0) {
    return 0;
  }
  const next = markdown.indexOf('\n## ', start + heading.length);
  return markdown
    .slice(start, next < 0 ? markdown.length : next)
    .split('\n')
    .filter((line) => line.startsWith('| ')).length;
};

/**
 * WBUX6-W4-A-05: maps whose `.md` has no `## Parity index` because it has never been
 * through the generator. Fail-closed in both directions — an unlisted map must have the
 * section, and a listed map must still be missing it, so enrolling a map forces the
 * exemption out (OBS-11: the bar ratchets up, it never tracks the current state).
 */
const MAPS_WITHOUT_PARITY_INDEX: Record<string, string> = {};

/**
 * WBUX6-W3-L3-03: the say/don`t-say table is hand-authored prose the structural renderer
 * cannot express, so `render_ux_maps.py` lifts it out of the existing md and re-injects it
 * verbatim. a1599b346 dropped it once already because nothing asserted it.
 */
const VOCABULARY_MAPS = ['workbench-2pane', 'roster-people'] as const;
const VOCABULARY_HEADING = "## Vocabulary (say / don't say)";

describe('ux-map generated-render provenance', () => {
  it('every owned md carries the generator parity index, or is a listed un-regenerated map', () => {
    const missing: string[] = [];
    const staleExemptions: string[] = [];
    for (const mapRef of OWNED_MAPS) {
      const { md } = loadOwnedMap(mapRef);
      const hasIndex = md.includes('\n## Parity index\n');
      const rationale = MAPS_WITHOUT_PARITY_INDEX[mapRef];
      if (rationale === undefined && !hasIndex) {
        missing.push(mapRef);
      }
      if (rationale !== undefined && hasIndex) {
        staleExemptions.push(mapRef);
      }
    }
    expect(missing, `owned md without a ## Parity index: ${missing.join(', ')}`).toEqual([]);
    expect(
      staleExemptions,
      `these maps now carry a parity index — remove them from MAPS_WITHOUT_PARITY_INDEX: ${staleExemptions.join(', ')}`,
    ).toEqual([]);
  });

  it('keeps the hand-authored vocabulary section in the md and in the renderer KEEP_SECTIONS', () => {
    const renderer = readFileSync(rendererPath, 'utf8');
    expect(renderer, 'render_ux_maps.py no longer preserves the vocabulary section').toContain(
      `"${VOCABULARY_HEADING}"`,
    );

    for (const mapRef of VOCABULARY_MAPS) {
      const { md, mdName } = loadOwnedMap(mapRef);
      expect(md, `${mdName} lost the say/don't-say table`).toContain(`\n${VOCABULARY_HEADING}\n`);
      const section = md.slice(md.indexOf(VOCABULARY_HEADING)).split('\n## ')[0] ?? '';
      const rows = section.split('\n').filter((line) => line.startsWith('| ') && !line.startsWith('| --- '));
      expect(rows.length, `${mdName} vocabulary table has no say/don't-say rows`).toBeGreaterThan(3);
    }
  });

  it('preserves the recovered operator and reducer contracts across regeneration', () => {
    const renderer = readFileSync(rendererPath, 'utf8');
    const operator = readFileSync(path.join(uxMapsDir, 'workbench-operator-loop.md'), 'utf8');
    const reducer = readFileSync(path.join(uxMapsDir, 'febt-1-job-error-states.md'), 'utf8');

    expect(renderer).toContain('"## Operator interaction contract"');
    expect(renderer).toContain('"## Detailed reducer and recovery contract"');
    for (const required of [
      'APP_LINK_PARAMS',
      'position: 1 of N on this page',
      'N of M faces shown',
      'Is this <name>? Yes/No',
      'busy disables actions',
      'zero reps still render (Avatar, not empty)',
      'WorkbenchFindingsPanel.tsx',
      'TopClusterCard.tsx',
      '([NAV-11])',
    ]) {
      expect(operator, `recovered operator contract lost: ${required}`).toContain(required);
    }
    expect(operator).toContain('n_workbench_scan -->|settings health| n_exit_settings');
    expect(reducer).toContain('### Reducer transition matrix');
    expect(reducer).toContain('### Pipeline banner examples');
    expect(reducer).toContain('### AppError banner and recovery rows');
    expect(reducer).toContain('### Stalled/offline reconciliation');
    expect(reducer).toContain('The reconnect counter is internal (`reconnectAttempts`) and never rendered');
    expect(
      sectionRows(reducer, '## Detailed reducer and recovery contract'),
      'recovered reducer contract must retain substantive tables',
    ).toBeGreaterThan(10);
  });

  it('every owned map describes a journey: non-empty flows and a source fixture', () => {
    const empty: string[] = [];
    for (const mapRef of OWNED_MAPS) {
      const raw = readMapJson(mapRef) as { flows?: unknown[]; source_fixture?: unknown };
      if (!Array.isArray(raw.flows) || raw.flows.length === 0) {
        empty.push(`${mapRef} flows`);
      }
      if (typeof raw.source_fixture !== 'string' || raw.source_fixture.length === 0) {
        empty.push(`${mapRef} source_fixture`);
      }
    }
    expect(
      empty,
      `WBUX6-W4-A-06: a map that validates while describing no journey is false coverage: ${empty.join(', ')}`,
    ).toEqual([]);
  });
});
