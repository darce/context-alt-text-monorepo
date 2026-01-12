import type { ClusterListParams } from './recognition/types';

export interface WorkbenchMediaParams {
  page: number;
  perPage: number;
  search?: string;
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
  suggestions: {
    all: ['suggestions'] as const,
    pending: () => [...queryKeys.suggestions.all, 'pending'] as const,
    identity: () => [...queryKeys.suggestions.all, 'identity'] as const,
    identityFor: (identityId: string | undefined) => [...queryKeys.suggestions.identity(), identityId] as const,
    inline: () => [...queryKeys.suggestions.all, 'inline'] as const,
    inlineFor: (identityId: string) => [...queryKeys.suggestions.inline(), identityId] as const,
  },
} as const;
