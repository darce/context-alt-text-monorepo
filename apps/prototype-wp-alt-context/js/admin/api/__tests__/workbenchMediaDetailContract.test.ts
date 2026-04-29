import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import Ajv from 'ajv';
import { describe, expect, expectTypeOf, it } from 'vitest';

import type { WorkbenchMediaDetail } from '../generated';

interface WorkbenchMediaDetailResponseSchema {
  $id?: string;
  required?: string[];
  additionalProperties?: WorkbenchMediaDetailResponseSchema;
  properties?: Record<string, { type?: string | string[] }>;
}

interface WorkbenchMediaDetailFixture {
  details_by_media: Record<string, WorkbenchMediaDetail>;
  limit: number;
  total: number;
  truncated: boolean;
}

describe('workbench media detail contract fixture', () => {
  const detailSchema = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/schemas/workbench-media-detail.schema.json'),
      'utf8',
    ),
  ) as WorkbenchMediaDetailResponseSchema;

  const schema = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/schemas/workbench-media-detail-response.schema.json'),
      'utf8',
    ),
  ) as WorkbenchMediaDetailResponseSchema;

  const fixture = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/recognition/workbench-media-detail-response.golden.json'),
      'utf8',
    ),
  ) as WorkbenchMediaDetailFixture;

  const ajv = new Ajv({ allErrors: true, schemaId: 'auto' });
  ajv.addSchema(detailSchema, detailSchema.$id ?? 'workbench-media-detail');

  it('declares the workbench media detail envelope in the shared schema', () => {
    expect(schema.required).toEqual(expect.arrayContaining(['details_by_media', 'limit', 'total', 'truncated']));
    expect(schema.properties?.details_by_media?.type).toBe('object');
    expect(schema.properties?.limit?.type).toBe('integer');
    expect(schema.properties?.total?.type).toBe('integer');
    expect(schema.properties?.truncated?.type).toBe('boolean');
  });

  it('validates the golden fixture against the shared schema', () => {
    const validate = ajv.compile(schema);

    expect(validate(fixture)).toBe(true);
    expect(validate.errors).toBeNull();
  });

  it('matches the frontend workbench media detail response shape', () => {
    const response: WorkbenchMediaDetailFixture = fixture;

    expectTypeOf(response.details_by_media).toMatchTypeOf<Record<string, WorkbenchMediaDetail>>();
    expect(response.limit).toBe(100);
    expect(response.total).toBe(2);
    expect(response.truncated).toBe(false);
    expect(response.details_by_media['11']?.updatedAt).toBe('2026-04-29T00:00:00+00:00');
    expect(response.details_by_media['11']?.mimeType).toBe('image/jpeg');
    expect(response.details_by_media['12']?.dimensions?.width).toBe(640);
  });
});