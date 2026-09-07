import type { QueryClient } from '@tanstack/react-query';

import type { WorkbenchMediaStatus } from './workbenchMediaApi';

import type { ClusterListParams } from './recognition/types';
import type { ConflictListParams, FailedOutboxListParams, OutboxListParams } from './recognition/conflictApi';

export interface WorkbenchMediaParams {
  page: number;
  perPage: number;
  search?: string;
  status?: WorkbenchMediaStatus;
}

export const queryKeys = {
  media: {
    all: ['media'] as const,
    identities: () => [...queryKeys.media.all, 'identities'] as const,
    identitiesByIds: (mediaIds: number[]) => [...queryKeys.media.identities(), mediaIds] as const,
    details: () => [...queryKeys.media.all, 'details'] as const,
    detailByIds: (mediaIds: number[]) => [...queryKeys.media.details(), mediaIds] as const,
    workbench: () => [...queryKeys.media.all, 'workbench'] as const,
    workbenchPage: (params: WorkbenchMediaParams) => [...queryKeys.media.workbench(), params] as const,
  },
  clusters: {
    all: ['clusters'] as const,
    lists: () => [...queryKeys.clusters.all, 'list'] as const,
    list: (params: ClusterListParams = {}) => [...queryKeys.clusters.lists(), params] as const,
    details: () => [...queryKeys.clusters.all, 'detail'] as const,
    detail: (clusterId: string | null) => [...queryKeys.clusters.details(), clusterId] as const,
    members: () => [...queryKeys.clusters.all, 'members'] as const,
    memberList: (clusterId: string) => [...queryKeys.clusters.members(), clusterId] as const,
    labels: () => [...queryKeys.clusters.all, 'labels'] as const,
    topUnlabeled: (tenantId: string) => [...queryKeys.clusters.all, 'top-unlabeled', tenantId] as const,
    labelSearch: (term: string) => [...queryKeys.clusters.all, 'label-search', term] as const,
  },
  jobs: {
    all: ['jobs'] as const,
    status: (jobId: string | null) => [...queryKeys.jobs.all, 'status', jobId] as const,
    batchRun: (runId: string | null) => [...queryKeys.jobs.all, 'batch-run', runId] as const,
  },
  roster: {
    all: ['roster'] as const,
    entries: () => [...queryKeys.roster.all, 'entries'] as const,
  },
  sync: {
    all: ['sync'] as const,
    status: () => [...queryKeys.sync.all, 'status'] as const,
    health: () => [...queryKeys.sync.all, 'health'] as const,
  },
  retention: {
    all: ['retention'] as const,
    status: () => [...queryKeys.retention.all, 'status'] as const,
    exportJob: (jobId: string) => [...queryKeys.retention.all, 'exportJob', jobId] as const,
    audit: (params: { limit?: number; offset?: number; event_type?: string }) =>
      [...queryKeys.retention.all, 'audit', params] as const,
  },
  conflicts: {
    all: ['conflicts'] as const,
    lists: () => [...queryKeys.conflicts.all, 'list'] as const,
    list: (params: ConflictListParams = {}) => [...queryKeys.conflicts.lists(), params] as const,
    details: () => [...queryKeys.conflicts.all, 'detail'] as const,
    detail: (id: number | null) => [...queryKeys.conflicts.details(), id] as const,
  },
  outbox: {
    all: ['outbox'] as const,
    lists: () => [...queryKeys.outbox.all, 'list'] as const,
    list: (params: OutboxListParams = {}) => [...queryKeys.outbox.lists(), params] as const,
    failed: () => [...queryKeys.outbox.all, 'failed'] as const,
    failedList: (params: FailedOutboxListParams = {}) => [...queryKeys.outbox.failed(), params] as const,
  },
  suggestions: {
    all: ['suggestions'] as const,
    mergePending: () => [...queryKeys.suggestions.all, 'merge'] as const,
    namePending: () => [...queryKeys.suggestions.all, 'name'] as const,
    /**
     * Unified assignment-suggestion projection (identity-keyed + review).
     * Nested under `suggestions.all` so root invalidation still reaches it.
     */
    projection: {
      all: ['suggestions', 'projection'] as const,
      identityBatch: (idsKey: string) => [...queryKeys.suggestions.projection.all, 'identity-batch', idsKey] as const,
      reviewPage: (offset: number) => [...queryKeys.suggestions.projection.all, 'review-page', offset] as const,
    },
  },
  dashboard: {
    all: ['dashboard'] as const,
    stats: () => [...queryKeys.dashboard.all, 'stats'] as const,
  },
  gpu: {
    all: ['gpu'] as const,
    status: () => [...queryKeys.gpu.all, 'status'] as const,
  },
} as const;

/**
 * Shared probe shape for dashboard coverage counters. Single definition so
 * the list-page predicate and useMediaStats keys cannot drift [DATA-14][RES-08].
 */
export const MEDIA_STATS_PROBE = {
  page: 1,
  perPage: 1,
} as const;

/**
 * Dashboard coverage probes reuse the workbench prefix with
 * `MEDIA_STATS_PROBE.perPage`. Prefix-invalidating
 * `queryKeys.media.workbench()` therefore remounts list rows *and* refetches
 * the total-media probe, whose count never changes on alt apply
 * [BR-77][RLSE-04][S6-F1].
 */
export const isWorkbenchListPageQuery = (query: { queryKey: readonly unknown[] }): boolean => {
  const [root, kind, params] = query.queryKey;
  if (root !== 'media' || kind !== 'workbench') {
    return false;
  }
  if (typeof params !== 'object' || params === null) {
    return false;
  }
  const perPage = (params as { perPage?: unknown }).perPage;
  return typeof perPage === 'number' && perPage !== MEDIA_STATS_PROBE.perPage;
};

/** Invalidate rendered workbench list pages only — never the stats probes. */
export const invalidateWorkbenchListPages = (queryClient: QueryClient): void => {
  void queryClient.invalidateQueries({
    predicate: isWorkbenchListPageQuery,
  });
};
