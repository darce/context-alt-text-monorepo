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
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../../components/ui/dialog';

interface ClusterReviewPanelProps {
  clusterId: string;
  onClose: () => void;
}

export const ClusterReviewPanel = ({ clusterId, onClose }: ClusterReviewPanelProps): React.JSX.Element => {
  const queryClient = useQueryClient();
  const [pendingRemovalIdentityId, setPendingRemovalIdentityId] = React.useState<string | null>(null);

  const {
    data: membersResponse,
    isLoading,
    isError,
  } = useQuery({
    queryKey: queryKeys.clusters.memberList(clusterId),
    queryFn: () => fetchClusterMembers(clusterId),
    enabled: Boolean(clusterId),
  });
  const members = membersResponse?.members ?? [];

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
    setPendingRemovalIdentityId(identityId);
  };

  const handleCancelRemoval = () => {
    setPendingRemovalIdentityId(null);
  };

  const handleConfirmRemoval = () => {
    if (!pendingRemovalIdentityId) {
      return;
    }

    const identityId = pendingRemovalIdentityId;
    setPendingRemovalIdentityId(null);
    removeMutation.mutate(identityId);
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
        ) : members.length > 0 ? (
          <div className="acx-cluster-review-panel__grid">
            {members.map((member) => (
              <div key={member.identity_id} className="acx-cluster-member-card">
                <div className="acx-cluster-member-card__thumbnail">
                  {member.thumb_url ? (
                    <img
                      src={member.thumb_url}
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

      <DialogRoot
        open={pendingRemovalIdentityId !== null}
        onOpenChange={(open) => {
          if (!open) {
            handleCancelRemoval();
          }
        }}
      >
        <DialogPortal>
          <DialogOverlay />
          <DialogContent>
            <div className="acx-queue-modal">
              <DialogTitle>{__('Remove cluster member', 'alt-context')}</DialogTitle>
              <DialogDescription>
                {__('Are you sure you want to remove this person from the cluster?', 'alt-context')}
              </DialogDescription>
              <div className="acx-queue-modal__actions">
                <button type="button" className="button" onClick={handleCancelRemoval}>
                  {__('Cancel', 'alt-context')}
                </button>
                <button type="button" className="button button-primary" onClick={handleConfirmRemoval}>
                  {__('Remove member', 'alt-context')}
                </button>
              </div>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </div>
  );
};
