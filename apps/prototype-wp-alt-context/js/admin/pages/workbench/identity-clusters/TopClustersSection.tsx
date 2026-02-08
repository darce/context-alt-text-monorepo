/**
 * Section showing top unlabeled clusters for curation.
 *
 * Displays clusters with the most members that haven't been labeled yet,
 * encouraging users to label them first to bootstrap the suggestion system.
 * Includes face thumbnails from cluster representatives.
 */

import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { __, _n, sprintf } from '@wordpress/i18n';

import { queryKeys } from '../../../api/queryKeys';
import { mergeCluster, updateClusterLabel } from '../../../api/recognition';
import { dismissCluster, fetchTopUnlabeledClusters } from '../../../api/recognition/clusterApi';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';
import type { BoundingBox } from '../../../api/recognition/types/identity';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';

interface TopClustersSectionProps {
  /** Tenant ID for API scoping */
  tenantId: string;
  /** Called when user clicks to label a cluster */
  onLabel: (clusterId: string) => void;
  /** Called when user clicks to review a cluster */
  onReview?: (clusterId: string) => void;
}

const TOP_UNLABELED_LIMIT = 20;

const resolveRepresentativeThumbUrl = (
  representative: TopUnlabeledCluster['representatives'][number],
): string | null => {
  const legacyThumbnail = (representative as { thumbnail_url?: string | null }).thumbnail_url;
  const rawUrl = representative.thumb_url ?? legacyThumbnail ?? null;
  if (typeof rawUrl !== 'string' || rawUrl.trim() === '') {
    return null;
  }
  return rawUrl;
};

const resolveRepresentativeCrop = (
  representative: TopUnlabeledCluster['representatives'][number],
): { mediaUrl: string; bbox: BoundingBox } | null => {
  const mediaUrl = representative.media_url;
  const bbox = representative.bbox;
  if (typeof mediaUrl !== 'string' || mediaUrl.trim() === '' || !bbox) {
    return null;
  }

  const x = Number(bbox.x);
  const y = Number(bbox.y);
  const width = Number(bbox.width);
  const height = Number(bbox.height);

  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(width) || !Number.isFinite(height)) {
    return null;
  }
  if (width <= 0 || height <= 0) {
    return null;
  }

  return {
    mediaUrl,
    bbox: { x, y, width, height },
  };
};

const getMostRepresentative = (
  representatives: TopUnlabeledCluster['representatives'],
): TopUnlabeledCluster['representatives'][number] | null => {
  if (!Array.isArray(representatives) || representatives.length === 0) {
    return null;
  }

  return representatives.reduce((best, current) => {
    if (!best) {
      return current;
    }
    if (current.is_pinned && !best.is_pinned) {
      return current;
    }
    return best;
  }, representatives[0] ?? null);
};

/**
 * Individual cluster card with face thumbnails and label action.
 */
const TopClusterCard = ({
  cluster,
  onLabel,
  onReview,
  onConfirmSuggestedLabel,
  onDismiss,
  isConfirming,
  isDismissing,
}: {
  cluster: TopUnlabeledCluster;
  onLabel: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
  onConfirmSuggestedLabel?: (
    clusterId: string,
    suggestedLabel: string,
    suggestedTargetClusterId?: string | null,
  ) => void;
  onDismiss?: (clusterId: string) => void;
  isConfirming?: boolean;
  isDismissing?: boolean;
}): React.JSX.Element => {
  const gridSizePx = 80;
  const gapPx = 2;
  const maxThumbs = 4;
  const faceCount = cluster.identity_count;
  const suggestedLabel =
    typeof cluster.suggested_label === 'string' && cluster.suggested_label.trim() !== ''
      ? cluster.suggested_label.trim()
      : null;
  const title = suggestedLabel
    ? `${__('Is this', 'alt-context')} ${suggestedLabel}?`
    : __('Name this person', 'alt-context');
  const representative = getMostRepresentative(cluster.representatives ?? []);
  const reps = suggestedLabel
    ? representative
      ? [representative]
      : []
    : (cluster.representatives ?? []).slice(0, maxThumbs);
  const columnCount = reps.length <= 1 ? 1 : 2;
  const cellSize = (gridSizePx - gapPx * (columnCount - 1)) / columnCount;
  const gridClassName =
    columnCount === 1 ? 'acx-top-cluster-card__grid acx-top-cluster-card__grid--single' : 'acx-top-cluster-card__grid';
  const isBusy = (isDismissing ?? false) || (isConfirming ?? false);
  const handleConfirmSuggestedLabelClick = () => {
    if (!suggestedLabel || !onConfirmSuggestedLabel) {
      return;
    }
    onConfirmSuggestedLabel(cluster.id, suggestedLabel, cluster.suggested_target_cluster_id);
  };
  const handleRejectSuggestedLabelClick = () => {
    if (onDismiss) {
      onDismiss(cluster.id);
      return;
    }
    onLabel(cluster.id);
  };

  return (
    <div className="acx-top-cluster-card">
      <div className="acx-top-cluster-card__faces">
        {reps.length > 0 ? (
          <div className={gridClassName}>
            {reps.map((rep) => {
              const cropData = resolveRepresentativeCrop(rep);
              const thumbUrl = resolveRepresentativeThumbUrl(rep);
              return (
                <div key={rep.id} className="acx-top-cluster-card__thumb acx-top-cluster-card__thumb--frame">
                  {cropData ? (
                    <FaceThumbnail
                      mediaUrl={cropData.mediaUrl}
                      bbox={cropData.bbox}
                      sizePx={cellSize}
                      shape="square"
                      alt=""
                      className="acx-top-cluster-card__thumb-image"
                    />
                  ) : thumbUrl ? (
                    <img src={thumbUrl} alt="" className="acx-top-cluster-card__thumb-image" />
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <span className="acx-top-cluster-card__thumb acx-top-cluster-card__thumb--placeholder" />
        )}
      </div>

      <div className="acx-top-cluster-card__content">
        <p className="acx-top-cluster-card__title">
          {suggestedLabel ? (
            <strong>{title}</strong>
          ) : (
            <button
              type="button"
              className="acx-top-cluster-card__title-action acx-identity-cluster__label acx-identity-cluster__label--action"
              onClick={() => onLabel(cluster.id)}
              disabled={isBusy}
              title={__('Open labeling form', 'alt-context')}
            >
              {title}
            </button>
          )}
        </p>
        <p className="acx-top-cluster-card__meta">
          {sprintf(_n('%d face in cluster', '%d faces in cluster', faceCount, 'alt-context'), faceCount)}
        </p>
      </div>

      <div className="acx-top-cluster-card__actions">
        {suggestedLabel && onConfirmSuggestedLabel ? (
          <>
            <button
              type="button"
              className="button button-primary acx-top-cluster-card__confirm-btn"
              onClick={handleConfirmSuggestedLabelClick}
              disabled={isBusy}
              title={__('Confirm suggested name', 'alt-context')}
            >
              {__('Yes', 'alt-context')}
            </button>
            <button
              type="button"
              className="button acx-top-cluster-card__reject-btn"
              onClick={handleRejectSuggestedLabelClick}
              disabled={isBusy}
              title={__('Reject suggestion for now', 'alt-context')}
            >
              {__('No', 'alt-context')}
            </button>
          </>
        ) : null}
        {onReview && (
          <button
            type="button"
            className="button acx-top-cluster-card__review-btn"
            onClick={() => onReview(cluster.id)}
            disabled={isBusy}
          >
            {__('Review', 'alt-context')}
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            className="button button-link acx-top-cluster-card__skip-btn"
            onClick={() => onDismiss(cluster.id)}
            disabled={isBusy}
            title={__('Skip this cluster for now', 'alt-context')}
          >
            {__('Skip', 'alt-context')}
          </button>
        )}
      </div>
    </div>
  );
};

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

  const { data: topClusters, isLoading } = useQuery<TopUnlabeledCluster[]>({
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
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

  if (!topClusters || topClusters.length === 0) {
    return null;
  }

  // Filter to only show clusters with more than 1 face (not singletons)
  const nonSingletons = [...topClusters]
    .filter((c) => c.identity_count > 1 && !hiddenClusterIds.has(c.id))
    .sort((a, b) => b.identity_count - a.identity_count);

  if (nonSingletons.length === 0) {
    return null;
  }

  return (
    <div className="acx-top-clusters-section">
      <h4 className="acx-top-clusters-section__title">{__('Name These People', 'alt-context')}</h4>
      <p className="acx-top-clusters-section__description">
        {__(
          'These clusters have multiple faces and need labels. Labeling them helps the system suggest names automatically.',
          'alt-context',
        )}
      </p>

      <div className="acx-top-clusters-section__list">
        {nonSingletons.map((cluster) => (
          <TopClusterCard
            key={cluster.id}
            cluster={cluster}
            onLabel={onLabel}
            onReview={onReview}
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
