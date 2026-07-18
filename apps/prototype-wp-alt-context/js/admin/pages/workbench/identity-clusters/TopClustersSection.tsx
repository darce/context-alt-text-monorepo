/**
 * Section showing top unlabeled clusters for curation.
 *
 * Displays clusters with the most members that haven't been labeled yet,
 * encouraging users to label them first to bootstrap the suggestion system.
 * Includes face thumbnails from cluster representatives.
 */

import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { __ } from '@wordpress/i18n';

import { queryKeys } from '../../../api/queryKeys';
import { dismissCluster, fetchTopUnlabeledClusters, mergeCluster, updateClusterLabel } from '../../../api/recognition';
import { DATA_SOURCE, PROJECTION_STATUS } from '../../../api/recognition/types/dataSource';
import { EmptyStateWarning } from './EmptyStateWarning';
import type { TopUnlabeledClustersResponse } from '../../../api/recognition/types/cluster';
import { invalidateSuggestionProjection } from './suggestionProjection';
import { TopClusterCard } from './TopClusterCard';

interface TopClustersSectionProps {
  /** Tenant ID for API scoping */
  tenantId: string;
  /** Called when user clicks to label a cluster */
  onLabel: (clusterId: string) => void;
  /** Called when user clicks to review a cluster */
  onReview?: (clusterId: string) => void;
}

const TOP_UNLABELED_LIMIT = 20;

/**
 * Section showing top unlabeled clusters with curation prompts.
 */
export const TopClustersSection = ({
  tenantId,
  onLabel,
  onReview,
}: TopClustersSectionProps): React.JSX.Element | null => {
  const queryClient = useQueryClient();
  const [hiddenClusterIds, setHiddenClusterIds] = React.useState<Set<string>>(new Set());
  const [dismissingClusterIds, setDismissingClusterIds] = React.useState<Set<string>>(new Set());
  const [confirmingClusterIds, setConfirmingClusterIds] = React.useState<Set<string>>(new Set());

  const {
    data: topUnlabeledResponse,
    isLoading,
    refetch,
  } = useQuery<TopUnlabeledClustersResponse>({
    queryKey: queryKeys.clusters.topUnlabeled(tenantId),
    queryFn: () => fetchTopUnlabeledClusters(tenantId, TOP_UNLABELED_LIMIT),
    staleTime: 60000, // 1 minute
    // This component unmounts when ClusterLabelingPanel opens (conditional render in
    // WorkbenchPage).  Data may change while unmounted, so always refetch on remount
    // to avoid showing a just-labeled cluster as still unlabeled.
    refetchOnMount: 'always',
  });

  const dismissMutation = useMutation({
    mutationFn: (clusterId: string) => dismissCluster(clusterId),
    onMutate: (clusterId: string) => {
      setDismissingClusterIds((prev) => {
        const next = new Set(prev);
        next.add(clusterId);
        return next;
      });
      // Optimistically hide dismissed cluster so the next one immediately surfaces.
      setHiddenClusterIds((prev) => {
        const next = new Set(prev);
        next.add(clusterId);
        return next;
      });
    },
    onError: (_error, clusterId) => {
      // Roll back optimistic hide if dismissal fails.
      setHiddenClusterIds((prev) => {
        const next = new Set(prev);
        next.delete(clusterId);
        return next;
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.topUnlabeled(tenantId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void invalidateSuggestionProjection(queryClient);
    },
    onSettled: (_data, _error, clusterId) => {
      setDismissingClusterIds((prev) => {
        const next = new Set(prev);
        next.delete(clusterId);
        return next;
      });
    },
  });

  const confirmSuggestedLabelMutation = useMutation({
    mutationFn: async ({
      clusterId,
      suggestedLabel,
      suggestedTargetClusterId,
    }: {
      clusterId: string;
      suggestedLabel: string;
      suggestedTargetClusterId?: string | null;
    }) => {
      const shouldMerge =
        typeof suggestedTargetClusterId === 'string' &&
        suggestedTargetClusterId.trim() !== '' &&
        suggestedTargetClusterId !== clusterId;
      if (shouldMerge) {
        await mergeCluster(clusterId, suggestedTargetClusterId, suggestedLabel);
        return;
      }
      await updateClusterLabel(clusterId, suggestedLabel);
    },
    onMutate: ({ clusterId }) => {
      setConfirmingClusterIds((prev) => {
        const next = new Set(prev);
        next.add(clusterId);
        return next;
      });
      // Optimistically hide confirmed cluster from naming queue.
      setHiddenClusterIds((prev) => {
        const next = new Set(prev);
        next.add(clusterId);
        return next;
      });
    },
    onError: (_error, { clusterId }) => {
      setHiddenClusterIds((prev) => {
        const next = new Set(prev);
        next.delete(clusterId);
        return next;
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.topUnlabeled(tenantId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void invalidateSuggestionProjection(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
    },
    onSettled: (_data, _error, { clusterId }) => {
      setConfirmingClusterIds((prev) => {
        const next = new Set(prev);
        next.delete(clusterId);
        return next;
      });
    },
  });

  if (isLoading) {
    return null; // Don't show loading state - suggestions panel handles that
  }

  const topClusters = topUnlabeledResponse?.clusters ?? [];
  const singletonCount = topUnlabeledResponse?.singleton_count ?? 0;
  const hasClusters = topUnlabeledResponse?.has_clusters;
  const dataSource = topUnlabeledResponse?.data_source;
  const projectionStatus = topUnlabeledResponse?.projection_status;
  const isReadOnly = dataSource === DATA_SOURCE.BACKEND_PROXY;

  if (!topUnlabeledResponse) {
    return null;
  }

  if (dataSource === DATA_SOURCE.UNAVAILABLE) {
    const isBootstrapping = projectionStatus === PROJECTION_STATUS.BOOTSTRAPPING;
    return (
      <div className="acx-top-clusters-section acx-top-clusters-section--empty">
        <h4 className="acx-top-clusters-section__title">{__('Name These People', 'alt-context')}</h4>
        <EmptyStateWarning
          title={
            isBootstrapping
              ? __('Local identities are still syncing', 'alt-context')
              : __('Naming queue unavailable', 'alt-context')
          }
          message={
            isBootstrapping
              ? __(
                  'The local projection is still being prepared. This queue will populate when sync completes.',
                  'alt-context',
                )
              : __('We could not load the naming queue right now.', 'alt-context')
          }
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (topClusters.length === 0 && singletonCount === 0) {
    if (dataSource === DATA_SOURCE.LOCAL_PROJECTION && hasClusters === false) {
      return (
        <div className="acx-top-clusters-section acx-top-clusters-section--empty">
          <h4 className="acx-top-clusters-section__title">{__('Name These People', 'alt-context')}</h4>
          <p className="acx-top-clusters-section__empty-message">
            {__('No recognized people are available yet. Run a scan to build the naming queue.', 'alt-context')}
          </p>
        </div>
      );
    }

    if (dataSource === DATA_SOURCE.LOCAL_PROJECTION && hasClusters === true) {
      return (
        <div className="acx-top-clusters-section acx-top-clusters-section--empty">
          <h4 className="acx-top-clusters-section__title">{__('Name These People', 'alt-context')}</h4>
          <p className="acx-top-clusters-section__empty-message">
            {__(
              'Everyone already has a label. New unlabeled groups will appear here after future scans.',
              'alt-context',
            )}
          </p>
        </div>
      );
    }

    return null;
  }

  const visibleClusters = [...topClusters]
    .sort((a, b) => b.identity_count - a.identity_count)
    .filter((cluster) => !hiddenClusterIds.has(cluster.id));

  if (topClusters.length === 0 && singletonCount > 0) {
    return (
      <div className="acx-top-clusters-section acx-top-clusters-section--empty">
        <h4 className="acx-top-clusters-section__title">{__('Name These People', 'alt-context')}</h4>
        <p className="acx-top-clusters-section__empty-message">
          {__(
            'All detected groups contain only a single photo. Groups with multiple photos will appear here.',
            'alt-context',
          )}
        </p>
      </div>
    );
  }

  if (visibleClusters.length === 0) {
    return null;
  }

  return (
    <div className="acx-top-clusters-section">
      <h4 className="acx-top-clusters-section__title">{__('Name These People', 'alt-context')}</h4>
      <p className="acx-top-clusters-section__description">
        {isReadOnly
          ? __(
              'These clusters are visible while local sync catches up. Curation stays disabled until projected results are available locally.',
              'alt-context',
            )
          : __(
              'These clusters have multiple faces and need labels. Labeling them helps the system suggest names automatically.',
              'alt-context',
            )}
      </p>

      <div className="acx-top-clusters-section__list">
        {visibleClusters.map((cluster) => (
          <TopClusterCard
            key={cluster.id}
            cluster={cluster}
            onLabel={onLabel}
            onReview={onReview}
            isReadOnly={isReadOnly}
            onConfirmSuggestedLabel={(clusterId, suggestedLabel, suggestedTargetClusterId) =>
              confirmSuggestedLabelMutation.mutate({ clusterId, suggestedLabel, suggestedTargetClusterId })
            }
            onDismiss={(id) => dismissMutation.mutate(id)}
            isConfirming={confirmingClusterIds.has(cluster.id)}
            isDismissing={dismissingClusterIds.has(cluster.id)}
          />
        ))}
      </div>
    </div>
  );
};
