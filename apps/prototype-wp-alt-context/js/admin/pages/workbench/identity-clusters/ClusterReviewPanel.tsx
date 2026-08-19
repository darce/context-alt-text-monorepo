/**
 * ClusterReviewPanel
 *
 * Controlled member-review pane for a single cluster id. Pure child: it renders
 * the live membership of `clusterId` and owns member removal + show-all paging.
 *
 * Open-target lifecycle (retirement rebind-else-close, E21-5 §11 / FBT-1 ⑤) is
 * NOT owned here — it lives in the always-mounted owner (ScanTabContent) via
 * `useOpenReviewTargetLifecycle`, which resolves the live target and swaps this
 * panel's `clusterId` (rebind) or unmounts it (close). Owning that here would
 * couple the rebind transition to this panel's own remount: the advance fires a
 * passive-effect update that unmounts the panel and remounts a new one, and in
 * the act-wrapped test harness that remount produces overlapping react-query
 * notifications which drop the batched update. The owner resolves the transition
 * render-phase against its own state instead. See `useOpenReviewTargetLifecycle`.
 *
 * Stale-membership guard (criterion 4): a retired cluster's members fetch 404s,
 * so `isError` short-circuits before the member grid — no stale faces paint even
 * during the brief window before the owner unmounts/rebinds this panel.
 */

import React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import { removeClusterMember } from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';
import { DurableFaceThumb } from '../../../../components/ui/DurableFaceThumb';
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../../components/ui/dialog';

import { invalidateSuggestionProjection } from './suggestionProjection';
import { useShowAllClusterMembers } from './useShowAllClusterMembers';

interface ClusterReviewPanelProps {
  clusterId: string;
  onClose: () => void;
}

export const ClusterReviewPanel = ({
  clusterId,
  onClose,
}: ClusterReviewPanelProps): React.JSX.Element => {
  const queryClient = useQueryClient();
  const [pendingRemovalIdentityId, setPendingRemovalIdentityId] = React.useState<string | null>(null);
  const [showAllAnnouncement, setShowAllAnnouncement] = React.useState<string | null>(null);
  const memberGridRef = React.useRef<HTMLDivElement | null>(null);
  const backButtonRef = React.useRef<HTMLButtonElement | null>(null);
  const wasExpandingRef = React.useRef(false);

  React.useEffect(() => {
    backButtonRef.current?.focus({ preventScroll: true });
  }, []);

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
    refetch,
  } = useShowAllClusterMembers(clusterId);

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
    <div className="acx-cluster-review-panel">
      <div className="acx-cluster-review-panel__header">
        <button
          type="button"
          className="acx-cluster-review-panel__back"
          ref={backButtonRef}
          onClick={onClose}
        >
          {__('← Back to Review Suggestions', 'alt-context')}
        </button>
        <h2 id="acx-workbench-queue-heading">{__('Review these faces', 'alt-context')}</h2>
      </div>

      <div className="acx-cluster-review-panel__content">
        {isLoading ? (
          <p>{__('Loading members...', 'alt-context')}</p>
        ) : isError ? (
          <div className="acx-cluster-review-panel__error" role="alert" data-testid="acx-cluster-members-error">
            <p>{__('Unable to load faces.', 'alt-context')}</p>
            <button type="button" className="button" onClick={() => refetch()}>
              {__('Retry', 'alt-context')}
            </button>
          </div>
        ) : members.length > 0 ? (
          <>
            <div className="acx-cluster-review-panel__grid" ref={memberGridRef} tabIndex={-1}>
              {members.map((member) => (
                <div key={member.identity_id} className="acx-cluster-member-card">
                  <div className="acx-cluster-member-card__thumbnail">
                    <DurableFaceThumb
                      source={{
                        thumbUrl: member.thumb_url,
                        attachmentUrl: member.attachment_url,
                        mediaUrl: member.media_url,
                        bbox: member.bbox,
                      }}
                      size="lg"
                      alt={sprintf(__('Face on media %d', 'alt-context'), member.media_id)}
                      className="acx-cluster-member-card__image"
                    />
                    <button
                      type="button"
                      className="acx-cluster-member-card__remove"
                      onClick={() => handleRemove(member.identity_id)}
                      aria-label={__('Remove this face from the face group', 'alt-context')}
                      title={__('Remove this face from the face group', 'alt-context')}
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
              <DialogTitle>{__('Remove this face', 'alt-context')}</DialogTitle>
              <DialogDescription>
                {__('Are you sure you want to remove this face from the face group?', 'alt-context')}
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
