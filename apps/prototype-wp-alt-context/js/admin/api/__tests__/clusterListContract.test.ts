import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, expectTypeOf, it } from 'vitest';

import type { ClusterListResponse } from '../recognition/types/cluster';

interface ClusterListSchema {
  required?: string[];
  properties?: Record<string, { type?: string | string[] }>;
}

describe('cluster list contract fixture', () => {
  const schema = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/schemas/recognition-cluster-list-response.schema.json'),
      'utf8',
    ),
  ) as ClusterListSchema;

  const fixture = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/recognition/cluster-list-response.golden.json'),
      'utf8',
    ),
  ) as ClusterListResponse;

  it('declares the cluster-list envelope in the shared schema', () => {
    expect(schema.required).toEqual(expect.arrayContaining(['clusters', 'limit', 'total', 'truncated']));
    expect(schema.properties?.clusters?.type).toBe('array');
    expect(schema.properties?.limit?.type).toBe('integer');
    expect(schema.properties?.total?.type).toBe('integer');
    expect(schema.properties?.truncated?.type).toBe('boolean');
  });

  it('matches the frontend cluster-list response shape', () => {
    const response: ClusterListResponse = fixture;

    expectTypeOf(response).toMatchTypeOf<ClusterListResponse>();
    expect(response.limit).toBe(2);
    expect(response.total).toBe(3);
    expect(response.truncated).toBe(true);
    expect(response.clusters).toHaveLength(2);
    expect(response.clusters[0]?.id).toBe('cluster-local-1');
    expect(response.clusters[0]?.sample_identities[0]?.identity_id).toBe('identity-local-1');
    expect(response.clusters[1]?.representative_identity.media_id).toBe(22);
  });
});
