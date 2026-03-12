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
  },
  roster: {
    all: ['roster'] as const,
    entries: () => [...queryKeys.roster.all, 'entries'] as const,
  },
  sync: {
    all: ['sync'] as const,
    status: () => [...queryKeys.sync.all, 'status'] as const,
  },
  retention: {
    all: ['retention'] as const,
    status: () => [...queryKeys.retention.all, 'status'] as const,
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
    pending: () => [...queryKeys.suggestions.all, 'pending'] as const,
    mergePending: () => [...queryKeys.suggestions.all, 'merge'] as const,
    identity: () => [...queryKeys.suggestions.all, 'identity'] as const,
    identityFor: (identityId: string | undefined) => [...queryKeys.suggestions.identity(), identityId] as const,
    inline: () => [...queryKeys.suggestions.all, 'inline'] as const,
    inlineFor: (identityId: string) => [...queryKeys.suggestions.inline(), identityId] as const,
  },
  dashboard: {
    all: ['dashboard'] as const,
    stats: () => [...queryKeys.dashboard.all, 'stats'] as const,
  },
} as const;
