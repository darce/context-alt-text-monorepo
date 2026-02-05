/**
 * Section showing top unlabeled clusters for curation.
 *
 * Displays clusters with the most members that haven't been labeled yet,
 * encouraging users to label them first to bootstrap the suggestion system.
 * Includes face thumbnails from cluster representatives.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { __, _n, sprintf } from '@wordpress/i18n';

import { fetchApi } from '../../../utils/http';
import { getEndpoint, getConfig } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';

interface TopClustersSectionProps {
  /** Tenant ID for API scoping */
  tenantId: string;
  /** Called when user clicks to label a cluster */
  onLabel: (clusterId: string) => void;
  /** Called when user clicks to review a cluster */
  onReview?: (clusterId: string) => void;
}

/**
 * Individual cluster card with face thumbnails and label action.
 */
const TopClusterCard = ({
  cluster,
  onLabel,
  onReview,
}: {
  cluster: TopUnlabeledCluster;
  onLabel: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
}): React.JSX.Element => {
  const faceCount = cluster.identity_count;
  const reps = cluster.representatives || [];
  const displayLabel = cluster.label?.startsWith('cluster-') ? __('Unnamed cluster', 'alt-context') : cluster.label;

  return (
    <div className="acx-top-cluster-card">
      <div className="acx-top-cluster-card__faces">
        {reps.length > 0 ? (
          <div
            className="acx-top-cluster-card__grid"
            style={{
              display: 'grid',
              gridTemplateColumns: `repeat(${Math.min(reps.length, 3)}, 1fr)`,
              gap: '2px',
              width: 'var(--acx-thumb-size-md, 80px)',
              height: 'var(--acx-thumb-size-md, 80px)',
              overflow: 'hidden',
              borderRadius: '4px',
            }}
          >
            {reps.slice(0, 3).map((rep) => (
              <div
                key={rep.id}
                className="acx-top-cluster-card__thumb"
                style={{
                  backgroundImage: rep.thumb_url ? `url(${rep.thumb_url})` : undefined,
                  backgroundColor: rep.thumb_url ? undefined : '#e0e0e0',
                  backgroundSize: 'cover',
                  backgroundPosition: 'center',
                  aspectRatio: '1',
                }}
              />
            ))}
          </div>
        ) : (
          <span className="acx-top-cluster-card__thumb acx-top-cluster-card__thumb--placeholder" />
        )}
      </div>

      <div className="acx-top-cluster-card__content">
        <p className="acx-top-cluster-card__title">
          <strong>{__('Name this person', 'alt-context')}</strong>
        </p>
        <p className="acx-top-cluster-card__meta">
          {sprintf(_n('%d face in cluster', '%d faces in cluster', faceCount, 'alt-context'), faceCount)}
        </p>
      </div>

      <div className="acx-top-cluster-card__actions">
        <button
          type="button"
          className="button button-primary acx-top-cluster-card__label-btn"
          onClick={() => onLabel(cluster.id)}
        >
          {__('Label', 'alt-context')}
        </button>
        {onReview && (
          <button
            type="button"
            className="button acx-top-cluster-card__review-btn"
            onClick={() => onReview(cluster.id)}
          >
            {__('Review', 'alt-context')}
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
  const { data: topClusters, isLoading } = useQuery<TopUnlabeledCluster[]>({
    queryKey: queryKeys.clusters.topUnlabeled(tenantId),
    queryFn: async () => {
      const base = getEndpoint('recognitionClusters');
      const url = `${base}/top-unlabeled?limit=5&tenant_id=${tenantId}`;
      return fetchApi<TopUnlabeledCluster[]>(url, {
        restNonce: getConfig().nonce,
      });
    },
    staleTime: 60000, // 1 minute
  });

  if (isLoading) {
    return null; // Don't show loading state - suggestions panel handles that
  }

  if (!topClusters || topClusters.length === 0) {
    return null;
  }

  // Filter to only show clusters with more than 1 face (not singletons)
  const nonSingletons = topClusters.filter((c) => c.identity_count > 1);

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
          <TopClusterCard key={cluster.id} cluster={cluster} onLabel={onLabel} onReview={onReview} />
        ))}
      </div>
    </div>
  );
};
