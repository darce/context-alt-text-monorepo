import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, expectTypeOf, it } from 'vitest';

import type { TopUnlabeledClustersResponse } from '../recognition/types/cluster';

interface TopUnlabeledSchema {
  required?: string[];
  properties?: Record<string, { type?: string | string[] }>;
}

describe('top-unlabeled clusters contract fixture', () => {
  const schema = JSON.parse(
    readFileSync(
      resolve(
        process.cwd(),
        '../../packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json',
      ),
      'utf8',
    ),
  ) as TopUnlabeledSchema;

  const fixture = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/recognition/cluster-top-unlabeled-response.golden.json'),
      'utf8',
    ),
  ) as TopUnlabeledClustersResponse;

  it('declares the top-unlabeled envelope in the shared schema', () => {
    expect(new Set(schema.required)).toEqual(
      new Set(['clusters', 'limit', 'total', 'truncated', 'data_source', 'repair_pending']),
    );
    expect(schema.properties?.clusters?.type).toBe('array');
    expect(schema.properties?.limit?.type).toBe('integer');
    expect(schema.properties?.total?.type).toBe('integer');
    expect(schema.properties?.truncated?.type).toBe('boolean');
    expect(schema.properties?.data_source?.type).toBe('string');
    expect(schema.properties?.repair_pending?.type).toBe('boolean');
  });

  it('matches the frontend top-unlabeled response shape', () => {
    const response: TopUnlabeledClustersResponse = fixture;

    expectTypeOf(response).toMatchTypeOf<TopUnlabeledClustersResponse>();
    expect(response.limit).toBe(10);
    expect(response.total).toBe(24);
    expect(response.truncated).toBe(true);
    expect(response.singleton_count).toBe(3);
    expect(response.data_source).toBe('local_projection');
    expect(response.projection_status).toBe('available');
    expect(response.clusters[0]?.representatives[0]?.media_id).toBe(101);
  });
});
