import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, expectTypeOf, it } from 'vitest';

import type { DetectedIdentity } from '../recognition/types/identity';

interface SnapshotCluster {
  cluster_uuid: string;
  label: string | null;
  curation_state: 'active' | 'confirmed' | 'dismissed';
  is_user_confirmed: boolean;
  identity_count: number;
  representative_thumb_path: string | null;
  representative_id: string | null;
  is_pinned: boolean;
  suggested_label: string | null;
  suggested_label_source: 'identity' | 'roster' | 'similar_cluster' | 'none' | null;
  suggested_label_confidence: number | null;
  suggested_target_cluster_id: string | null;
}

interface SnapshotMember {
  identity_uuid: string;
  cluster_uuid: string;
  attachment_id: number;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  image_width: number;
  image_height: number;
  thumb_path: string;
  similarity: number;
}

interface SnapshotFixture {
  tenant_id: string;
  snapshot_version: number;
  snapshot_generation_id: string | null;
  source_job_id: string | null;
  generated_at: string;
  clusters: SnapshotCluster[];
  members: SnapshotMember[];
}

describe('cluster snapshot contract fixture', () => {
  const fixture = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/recognition/cluster-snapshot.golden.json'),
      'utf8',
    ),
  ) as SnapshotFixture;

  it('matches the expected snapshot payload shape', () => {
    const snapshot: SnapshotFixture = fixture;

    expect(snapshot.snapshot_version).toBe(104);
    expect(snapshot.clusters).toHaveLength(2);
    expect(snapshot.members).toHaveLength(3);
    expect(snapshot.clusters[0]?.representative_id).toBe('4b8f0a3e-3f1f-4f59-96f2-bfb6c8c1d3bb');
    expect(snapshot.clusters[0]?.is_pinned).toBe(true);
    expect(snapshot.clusters[1]?.suggested_target_cluster_id).toBe('6c1a2e32-31b2-4d54-a4de-98b1a73d77a1');
  });

  it('can be mapped into frontend identity records without contract gaps', () => {
    const snapshot: SnapshotFixture = fixture;
    const clusterById = new Map(snapshot.clusters.map((cluster) => [cluster.cluster_uuid, cluster]));

    const identities = snapshot.members.map((member) => {
      const cluster = clusterById.get(member.cluster_uuid);
      return {
        identity_id: member.identity_uuid,
        representative_id: cluster?.representative_id ?? null,
        media_id: member.attachment_id,
        cluster_id: member.cluster_uuid,
        cluster_label: cluster?.label ?? null,
        is_auto_label: false,
        is_pinned: cluster?.is_pinned ?? false,
        bbox: member.bbox,
        confidence: member.similarity,
        similarity: member.similarity,
        thumb_url: member.thumb_path,
      };
    });

    expectTypeOf(identities).toMatchTypeOf<DetectedIdentity[]>();
    expect(identities[0]?.cluster_label).toBe('Alice Example');
    expect(identities[0]?.is_pinned).toBe(true);
    expect(identities[2]?.cluster_label).toBeNull();
  });
});
