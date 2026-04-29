import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, expectTypeOf, it } from 'vitest';

import type { ClusterLabelsResponse } from '../recognition/types/cluster';

interface ClusterLabelsSchema {
  required?: string[];
  properties?: Record<string, { type?: string | string[] }>;
}

describe('cluster labels contract fixture', () => {
  const schema = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/schemas/recognition-cluster-labels-response.schema.json'),
      'utf8',
    ),
  ) as ClusterLabelsSchema;

  const fixture = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/recognition/cluster-labels-response.golden.json'),
      'utf8',
    ),
  ) as ClusterLabelsResponse;

  it('declares the cluster-labels envelope in the shared schema', () => {
    expect(schema.required).toEqual(expect.arrayContaining(['labels', 'limit', 'total', 'truncated']));
    expect(schema.properties?.labels?.type).toBe('array');
    expect(schema.properties?.limit?.type).toBe('integer');
    expect(schema.properties?.total?.type).toBe('integer');
    expect(schema.properties?.truncated?.type).toBe('boolean');
  });

  it('matches the frontend cluster-labels response shape', () => {
    const response: ClusterLabelsResponse = fixture;

    expectTypeOf(response).toMatchTypeOf<ClusterLabelsResponse>();
    expect(response.labels).toEqual(['Alice Example', 'Alicia Example']);
    expect(response.limit).toBe(2);
    expect(response.total).toBe(3);
    expect(response.truncated).toBe(true);
  });
});