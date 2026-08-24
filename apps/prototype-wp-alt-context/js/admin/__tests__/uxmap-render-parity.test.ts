/**
 * UX-map SSOT guard for every map under docs/ux-maps/. Two layers:
 *
 *  1. **Schema conformance** — every owned `*.uxmap.json` must validate against the
 *     canonical `UxMap` model (`workbay_canvas_mcp/ux_map/models.py`), mirrored here
 *     in TypeScript so the guard runs in-process with no Python dependency.
 *  2. **Render parity** — owned json labels must appear verbatim in the sibling `*.md`,
 *     and labels the json has since renamed must not linger there.
 *
 * DEMO-UX-1-D-15: `loadOwnedMap` used to do `JSON.parse(...) as UxMapDoc` — a
 * compile-time cast with zero runtime checking — so the parity guard stayed green
 * while every committed SSOT was structurally unloadable by the Python renderer that
 * owns the schema (DRIFT-03: an SSOT that cannot be loaded has stopped being a source
 * of truth). The cast is now a validated parse.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const uxMapsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/ux-maps');

const OWNED_MAPS = ['roster-people', 'workbench-2pane', 'workbench-operator-loop'] as const;

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

const MAP_STATES = [
  'default',
  'loading',
  'empty',
  'error',
  'offline',
  'first_time',
  'edge_input',
  'degraded',
] as const;

const ZONE_ROLES = [
  'content',
  'nav',
  'status',
  'queue',
  'job',
  'ai_review',
  'forced_choice',
  'form',
  'other',
] as const;

const SCREEN_KINDS = ['screen', 'overlay', 'exit'] as const;

const ACTION_HIERARCHIES = ['primary', 'secondary', 'tertiary', 'destructive'] as const;

/* ------------------------------------------------------------------ *
 * Strict model specs (pydantic `extra="forbid"` semantics).
 * ------------------------------------------------------------------ */

type ModelSpec = { name: string; fields: Record<string, FieldSpec> };

type FieldSpec =
  | { kind: 'str'; required?: boolean; nullable?: boolean }
  | { kind: 'bool'; required?: boolean }
  | { kind: 'int'; required?: boolean; nullable?: boolean }
  | { kind: 'enum'; values: readonly string[]; required?: boolean; nullable?: boolean }
  | { kind: 'strList' }
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
  },
};

/* ------------------------------------------------------------------ *
 * Validator
 * ------------------------------------------------------------------ */

type Issue = { loc: string; type: string; input: unknown };

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
      if (spec.nullable && value === null) return;
      if (typeof value !== 'string') issues.push({ loc, type: 'string_type', input: value });
      return;
    case 'bool':
      if (typeof value !== 'boolean') issues.push({ loc, type: 'bool_type', input: value });
      return;
    case 'int':
      if (spec.nullable && value === null) return;
      if (typeof value !== 'number' || !Number.isInteger(value)) {
        issues.push({ loc, type: 'int_type', input: value });
      }
      return;
    case 'enum':
      if (spec.nullable && value === null) return;
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
    if (!(key in spec.fields)) {
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
  if (!isRecord(doc)) return;

  const collect = (key: string): string[] => {
    const rows = doc[key];
    if (!Array.isArray(rows)) return [];
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
    if (!isRecord(screen) || !Array.isArray(screen.zones)) return;
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

/* ------------------------------------------------------------------ *
 * Typed view of the parts the parity assertions read.
 * ------------------------------------------------------------------ */

type UxMapZone = { id: string; label: string };
type UxMapScreen = { id: string; title: string; zones?: UxMapZone[] };
type UxMapDoc = { screens: UxMapScreen[] };

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
  for (const mapRef of OWNED_MAPS) {
    it(`${mapRef}.uxmap.json validates against the canonical UxMap schema`, () => {
      const issues = validateUxMap(readMapJson(mapRef));
      expect(
        formatIssues(issues),
        `${mapRef}.uxmap.json: ${issues.length} schema errors`,
      ).toEqual([]);
    });
  }
});

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
