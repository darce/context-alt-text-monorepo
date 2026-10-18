import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { DetectedIdentity } from '../../../api/recognition';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../../components/ui/dialog';
import { EmptyState, EmptyStateVariant } from '../../../components/ui/EmptyState';

interface AnchorSelectionModalProps {
  isOpen: boolean;
  label: string | null;
  members: DetectedIdentity[];
  onClose: () => void;
  onSelectAnchor: (identityId: string) => void;
}

export const AnchorSelectionModal = ({
  isOpen,
  label,
  members,
  onClose,
  onSelectAnchor,
}: AnchorSelectionModalProps): React.JSX.Element => {
  const handleOpenChange = React.useCallback(
    (open: boolean) => {
      if (!open) {
        onClose();
      }
    },
    [onClose],
  );

  const handleSelect = React.useCallback(
    (identityId: string) => {
      onSelectAnchor(identityId);
      onClose();
    },
    [onClose, onSelectAnchor],
  );

  const title = label
    ? sprintf(__('Keep "%s" with:', 'alt-context'), label)
    : __('Select the correct person', 'alt-context');

  return (
    <DialogRoot open={isOpen} onOpenChange={handleOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogContent>
          <div className="acx-anchor-modal">
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              {__(
                'Choose the face that should keep this cluster label. Other faces will move to a new cluster.',
                'alt-context',
              )}
            </DialogDescription>

            {members.length === 0 ? (
              <EmptyState
                variant={EmptyStateVariant.EMPTY}
                heading={__('No faces available to select.', 'alt-context')}
                body={__('Return to review suggestions and choose another face group.', 'alt-context')}
                action={{ label: __('Back to review suggestions', 'alt-context'), onClick: onClose }}
                headingLevel={3}
                className="acx-anchor-modal__empty"
              />
            ) : (
              <div className="acx-anchor-modal__grid">
                {members.map((member) => {
                  const hasThumbnail = Boolean(member.media_url && member.bbox);
                  const buttonLabel = sprintf(__('Use face from media #%d', 'alt-context'), member.media_id);

                  return (
                    <button
                      key={member.identity_id}
                      type="button"
                      className="acx-anchor-modal__option"
                      aria-label={buttonLabel}
                      onClick={() => handleSelect(member.identity_id)}
                    >
                      {hasThumbnail ? (
                        <FaceThumbnail
                          mediaUrl={member.media_url!}
                          bbox={member.bbox}
                          size="lg"
                          alt={buttonLabel}
                          className="acx-anchor-modal__thumb"
                        />
                      ) : (
                        <span className="acx-anchor-modal__thumb acx-anchor-modal__thumb--placeholder" />
                      )}
                      <span className="acx-anchor-modal__meta">
                        {sprintf(__('Media #%d', 'alt-context'), member.media_id)}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {members.length > 0 ? (
              <div className="acx-anchor-modal__actions">
                <DialogClose asChild>
                  <button type="button" className="button">
                    {__('Cancel', 'alt-context')}
                  </button>
                </DialogClose>
              </div>
            ) : null}
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};
