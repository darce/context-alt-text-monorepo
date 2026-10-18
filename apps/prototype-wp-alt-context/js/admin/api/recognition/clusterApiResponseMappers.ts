import type { MergeClusterResponse } from './types';

export const normalizeMergeClusterResponse = (
  sourceId: string,
  targetLabel: string | undefined,
  response: unknown,
): MergeClusterResponse => {
  const payload = (response ?? {}) as Record<string, unknown>;

  if (typeof payload.source_id === 'string' && typeof payload.target_id === 'string') {
    return payload as unknown as MergeClusterResponse;
  }

  if (typeof payload.source_cluster_id === 'string' && typeof payload.target_cluster_id === 'string') {
    return {
      source_id: payload.source_cluster_id,
      source_label: typeof payload.source_label === 'string' ? payload.source_label : null,
      target_id: payload.target_cluster_id,
      target_label: typeof payload.target_label === 'string' ? payload.target_label : (targetLabel ?? null),
      identities_moved: typeof payload.moved_identity_count === 'number' ? payload.moved_identity_count : 0,
      moved_identity_ids: Array.isArray(payload.moved_identity_ids)
        ? payload.moved_identity_ids.filter((value): value is string => typeof value === 'string')
        : [],
      target_identity_count: typeof payload.target_identity_count === 'number' ? payload.target_identity_count : 0,
    };
  }

  return {
    source_id: sourceId,
    source_label: null,
    target_id: typeof payload.id === 'string' ? payload.id : '',
    target_label: typeof payload.label === 'string' ? payload.label : (targetLabel ?? null),
    identities_moved: 0,
    moved_identity_ids: [],
    target_identity_count: typeof payload.identity_count === 'number' ? payload.identity_count : 0,
  };
};
