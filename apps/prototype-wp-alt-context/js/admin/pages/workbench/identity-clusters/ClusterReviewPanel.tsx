/**
 * ClusterReviewPanel
 *
 * Scaffolding stub for cluster review UI.
 */

import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { __ } from '@wordpress/i18n';

import { fetchClusterMembers, removeClusterMember } from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';

interface ClusterReviewPanelProps {
  clusterId: string;
  onClose: () => void;
}

export const ClusterReviewPanel = ({ clusterId, onClose }: ClusterReviewPanelProps): React.JSX.Element => {
  const queryClient = useQueryClient();

  const {
    data: members,
    isLoading,
    isError,
  } = useQuery({
    queryKey: queryKeys.clusters.memberList(clusterId),
    queryFn: () => fetchClusterMembers(clusterId),
    enabled: Boolean(clusterId),
  });

  const removeMutation = useMutation({
    mutationFn: (identityId: string) => removeClusterMember(identityId, true),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.memberList(clusterId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      // Invalidate suggestions as removal triggers recalibration
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
    },
  });

  const handleRemove = (identityId: string) => {
    if (window.confirm(__('Are you sure you want to remove this person from the cluster?', 'alt-context'))) {
      removeMutation.mutate(identityId);
    }
  };

  return (
    <div className="acx-cluster-review-panel">
      <div className="acx-cluster-review-panel__header">
        <h2>{__('Review Cluster', 'alt-context')}</h2>
        <button type="button" className="acx-close-button" onClick={onClose} aria-label={__('Close', 'alt-context')}>
          ×
        </button>
      </div>

      <div className="acx-cluster-review-panel__content">
        {isLoading ? (
          <p>{__('Loading members...', 'alt-context')}</p>
        ) : isError ? (
          <p>{__('Unable to load cluster members.', 'alt-context')}</p>
        ) : members && members.length > 0 ? (
          <div className="acx-cluster-review-panel__grid">
            {members.map((member) => (
              <div key={member.identity_id} className="acx-cluster-member-card">
                <div className="acx-cluster-member-card__thumbnail">
                  {member.thumbnail_url ? (
                    <img
                      src={member.thumbnail_url}
                      alt={__('Cluster member', 'alt-context')}
                      className="acx-cluster-member-card__image"
                    />
                  ) : member.media_url && member.bbox ? (
                    <FaceThumbnail
                      mediaUrl={member.media_url}
                      bbox={member.bbox}
                      size="lg"
                      alt={__('Cluster member', 'alt-context')}
                    />
                  ) : (
                    <div className="acx-placeholder" />
                  )}
                  <button
                    type="button"
                    className="acx-cluster-member-card__remove"
                    onClick={() => handleRemove(member.identity_id)}
                    aria-label={__('Remove from cluster', 'alt-context')}
                    title={__('Remove from cluster', 'alt-context')}
                  >
                    ×
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p>{__('No members found.', 'alt-context')}</p>
        )}
      </div>
    </div>
  );
};
