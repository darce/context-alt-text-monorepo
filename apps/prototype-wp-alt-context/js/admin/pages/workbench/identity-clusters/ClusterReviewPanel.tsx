/**
 * ClusterReviewPanel
 *
 * Scaffolding stub for cluster review UI.
 * Open-target lifecycle: live-derived rebind-else-close (E21-5 §11 / FBT-1 ⑤).
 */

import React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import { removeClusterMember } from '../../../api/recognition';
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
import { useClusterPanel } from '../ClusterPanelContext';
import { useMergeSurvivors } from './MergeSurvivorContext';
import { invalidateSuggestionProjection } from './suggestionProjection';
import { useLiveReviewTarget } from './useLiveReviewTarget';
import { useShowAllClusterMembers } from './useShowAllClusterMembers';

const isDedicatedFaceThumbUrl = (thumbUrl: string | null | undefined): boolean => {
  return typeof thumbUrl === 'string' && thumbUrl.includes('recognition/face-thumbs/');
};

interface ClusterReviewPanelProps {
  clusterId: string;
  onClose: () => void;
  /** Focus the queue root anchor after retirement close (A11Y-21 companion). */
  onFocusQueueRoot?: () => void;
  /**
   * Lifecycle (retirement/rebind) announce sink owned by the parent. The panel
   * is remounted on rebind (key change) and unmounted on close, so its own
   * state cannot carry the A11Y-21 announce across the transition — the owner
   * renders the persistent `role=status` region that survives both.
   */
  onLifecycleAnnounce?: (message: string) => void;
}

export const ClusterReviewPanel = ({
  clusterId,
  onClose,
  onFocusQueueRoot,
  onLifecycleAnnounce,
}: ClusterReviewPanelProps): React.JSX.Element => {
  const queryClient = useQueryClient();
  const { dispatchClusterPanel } = useClusterPanel();
  const { resolveSurvivor } = useMergeSurvivors();
  const [pendingRemovalIdentityId, setPendingRemovalIdentityId] = React.useState<string | null>(null);
  const [showAllAnnouncement, setShowAllAnnouncement] = React.useState<string | null>(null);
  const memberGridRef = React.useRef<HTMLDivElement | null>(null);
  const wasExpandingRef = React.useRef(false);

  const { status: liveTargetStatus } = useLiveReviewTarget(clusterId, {
    resolveSurvivor: (retiredId) => resolveSurvivor(retiredId),
    onAnnounce: (message) => onLifecycleAnnounce?.(message),
    onRebind: (survivorId) => {
      dispatchClusterPanel({ type: 'open_review', clusterId: survivorId });
    },
    onClose: () => {
      onClose();
      onFocusQueueRoot?.();
    },
  });

  const {
    members,
    isLoading,
    isError,
    truncated,
    total,
    isFullyLoaded,
    isExpanding,
    expandError,
    showAll,
  } = useShowAllClusterMembers(clusterId);

  // Criterion 4: never paint retired/stale membership after retirement is known.
  const suppressStaleMembership = liveTargetStatus === 'retired' || liveTargetStatus === 'rebound';

  // AT affordance: when expansion completes the show-all button unmounts, so
  // announce completion and move focus to the member grid before it drops.
  React.useEffect(() => {
    if (wasExpandingRef.current && !isExpanding && isFullyLoaded && !expandError) {
      setShowAllAnnouncement(
        sprintf(
          /* translators: %d: total member count */
          __('All %d members shown', 'alt-context'),
          total,
        ),
      );
      memberGridRef.current?.focus();
    }
    wasExpandingRef.current = isExpanding;
  }, [isExpanding, isFullyLoaded, expandError, total]);

  const removeMutation = useMutation({
    mutationFn: (identityId: string) => removeClusterMember(identityId, true),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.memberList(clusterId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      // Removal recalibrates assignment suggestions — shared projection family.
      void invalidateSuggestionProjection(queryClient);
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
    <div className="acx-cluster-review-panel" data-live-target-status={liveTargetStatus}>
      <div className="acx-cluster-review-panel__header">
        <h2>{__('Review Cluster', 'alt-context')}</h2>
        <button type="button" className="acx-close-button" onClick={onClose} aria-label={__('Close', 'alt-context')}>
          ×
        </button>
      </div>

      <div className="acx-cluster-review-panel__content">
        {suppressStaleMembership ? (
          <p>{__('This review target is no longer available.', 'alt-context')}</p>
        ) : isLoading ? (
          <p>{__('Loading members...', 'alt-context')}</p>
        ) : isError ? (
          <p>{__('Unable to load cluster members.', 'alt-context')}</p>
        ) : members.length > 0 ? (
          <>
            <div className="acx-cluster-review-panel__grid" ref={memberGridRef} tabIndex={-1}>
              {members.map((member) => (
                <div key={member.identity_id} className="acx-cluster-member-card">
                  <div className="acx-cluster-member-card__thumbnail">
                    {member.thumb_url && isDedicatedFaceThumbUrl(member.thumb_url) ? (
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
                    ) : member.thumb_url ? (
                      <img
                        src={member.thumb_url}
                        alt={__('Cluster member', 'alt-context')}
                        className="acx-cluster-member-card__image"
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
            <p className="acx-cluster-members-show-all__announce" role="status" aria-live="polite">
              {showAllAnnouncement}
            </p>
            {truncated && !isFullyLoaded ? (
              <div className="acx-cluster-members-show-all">
                <button
                  type="button"
                  className="button acx-cluster-members-show-all__button"
                  onClick={() => {
                    void showAll();
                  }}
                  disabled={isExpanding}
                  data-truncated={truncated ? 'true' : 'false'}
                  data-total={total}
                >
                  {isExpanding
                    ? __('Loading all members…', 'alt-context')
                    : sprintf(
                        /* translators: %d: total member count */
                        __('Show all (%d)', 'alt-context'),
                        total,
                      )}
                </button>
                {expandError ? (
                  <p className="acx-cluster-members-show-all__error" role="alert">
                    {expandError}
                  </p>
                ) : null}
              </div>
            ) : null}
          </>
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
