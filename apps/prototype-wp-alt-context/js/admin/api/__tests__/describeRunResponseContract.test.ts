import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, expectTypeOf, it } from 'vitest';

import type { DescribeRunResponse } from '../describeApi';

/**
 * The GATE referenced by the WBUX6-MRG-03 comment on DescribeRunResponse. That
 * comment promised this file; it did not exist, so the tightened contract had
 * no guard of its own and the only thing holding it up was six fixtures.
 *
 * DOM-03 (engineering.md:528): `recognition_enabled` names two different things
 * here and they must not be conflated. On SettingsResponse it is the operator's
 * *current* site setting. On DescribeRunResponse it is a *snapshot taken at
 * submit* of that setting -- scene/interface_adapters/http/schemas/responses.py
 * ("HARM-F1: snapshot of recognition_enabled at submit"), forwarded by the WP
 * proxy as RecognitionPolicy::enabled() in src/api/class-describe-controller.php.
 * The TS client never sends it. A run's flag reports the world the run executed
 * in, not the world the operator is looking at now.
 */

interface DescribeRunSchema {
  required?: string[];
  properties?: Record<string, { type?: string | string[] }>;
  additionalProperties?: boolean;
}

/**
 * Declared in the schema but deliberately NOT in `required`: additive, and
 * null for runs not created through POST /scene/describe/run. It is mirrored
 * on the TS interface all the same, because the alternative -- each consumer
 * bolting it on with `DescribeRunResponse & { deadline_seconds?: number }` --
 * means a rename in the schema produces no compile error anywhere, only a
 * silent fall-through to whatever local default that consumer invented
 * (rg-005, rg-015).
 */
const DESCRIBE_RUN_RESPONSE_OPTIONAL_KEYS = ['deadline_seconds'] as const;

/** Single canonical key list for the envelope (sr-007), mirrored against the schema. */
const DESCRIBE_RUN_RESPONSE_KEYS = [
  'tenant_id',
  'run_id',
  'status',
  'phase',
  'completed',
  'failed',
  'skipped',
  'total',
  'cancel_requested',
  'eta_seconds',
  'gpu_state',
  'recognition_enabled',
] as const;

type AssertTrue<T extends true> = T;

/**
 * Compile-time pins. These are checked by `tsc --noEmit` over the whole
 * project, not only by `vitest --typecheck`, so re-widening the field cannot
 * land green (sr-001: fix the code, never relax the check).
 *
 * If `recognition_enabled` were optional, an object without it would still
 * satisfy DescribeRunResponse -- so the Omit would extend it and this resolves
 * to `false`, which AssertTrue rejects.
 */
export type RecognitionEnabledIsRequired = AssertTrue<
  Omit<DescribeRunResponse, 'recognition_enabled'> extends DescribeRunResponse ? false : true
>;

/** Nullable or optional widening makes the tuple comparison fail. */
export type RecognitionEnabledIsNonNullableBoolean = AssertTrue<
  [DescribeRunResponse['recognition_enabled']] extends [boolean] ? true : false
>;

describe('DescribeRunResponse contract', () => {
  const schema = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/schemas/scene-describe-run.schema.json'),
      'utf8',
    ),
  ) as DescribeRunSchema;

  const fixture: DescribeRunResponse = {
    tenant_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    run_id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
    status: 'running',
    phase: 'describing',
    completed: 1,
    failed: 0,
    skipped: 0,
    total: 4,
    cancel_requested: false,
    eta_seconds: null,
    gpu_state: null,
    recognition_enabled: true,
  };

  it('keeps the TS interface key-for-key with the shared schema', () => {
    // The schema is additionalProperties:false, so `required` IS the envelope.
    expect(schema.additionalProperties).toBe(false);
    expect([...(schema.required ?? [])].sort()).toEqual([...DESCRIBE_RUN_RESPONSE_KEYS].sort());
    expect(Object.keys(fixture).sort()).toEqual([...DESCRIBE_RUN_RESPONSE_KEYS].sort());
    expectTypeOf(fixture).toMatchTypeOf<DescribeRunResponse>();
  });

  it('mirrors the optional deadline_seconds field instead of leaving it to local intersections', () => {
    const declared = Object.keys(schema.properties ?? {});

    for (const key of DESCRIBE_RUN_RESPONSE_OPTIONAL_KEYS) {
      expect(declared, key).toContain(key);
      expect(schema.required ?? [], key).not.toContain(key);
    }
    // Optional AND nullable on the wire, so the TS field has to admit both.
    expect(schema.properties?.deadline_seconds?.type).toEqual(['number', 'null']);
    expectTypeOf<DescribeRunResponse['deadline_seconds']>().toEqualTypeOf<number | null | undefined>();

    // The envelope is still exactly required + the optional keys, so a new
    // schema property added without a TS field fails here rather than silently.
    expect([...declared].sort()).toEqual(
      [...DESCRIBE_RUN_RESPONSE_KEYS, ...DESCRIBE_RUN_RESPONSE_OPTIONAL_KEYS].sort(),
    );
  });

  it('accepts a disclosed budget without disturbing the required envelope', () => {
    const disclosed: DescribeRunResponse = { ...fixture, deadline_seconds: 180 };

    expect(disclosed.deadline_seconds).toBe(180);
    expectTypeOf(disclosed).toMatchTypeOf<DescribeRunResponse>();
  });

  it('requires recognition_enabled as a plain boolean, never null and never absent', () => {
    expect(schema.required).toContain('recognition_enabled');
    // A `["boolean","null"]` union in the schema would mean the TS type lies.
    expect(schema.properties?.recognition_enabled?.type).toBe('boolean');
    expectTypeOf(fixture.recognition_enabled).toEqualTypeOf<boolean>();
  });

  it('carries both worlds -- a recognition-off run is a legal response', () => {
    const off: DescribeRunResponse = { ...fixture, recognition_enabled: false };

    expect(off.recognition_enabled).toBe(false);
    expect(Object.keys(off).sort()).toEqual([...DESCRIBE_RUN_RESPONSE_KEYS].sort());
  });
});
