/**
 * Cluster thumbnail preview with member count badge.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import type { DetectedIdentity } from '../../../api/recognition';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';

interface ClusterPreviewProps {
  /** First member to show as representative thumbnail */
  representative: DetectedIdentity | undefined;
  /** Total number of members in the cluster */
  memberCount: number;
  /** Called when the representative pin state should be toggled */
  onTogglePin?: (representative: DetectedIdentity, nextPinned: boolean) => void;
  /** Whether the pin toggle is currently in flight */
  isPinning?: boolean;
}

/**
 * Displays the cluster's representative thumbnail with an optional count badge.
 * The thumbnail shows the face cropped from the original image using InsightFace bbox.
 */
export const ClusterPreview = ({
  representative,
  memberCount,
  onTogglePin,
  isPinning = false,
}: ClusterPreviewProps): React.JSX.Element => {
  const hasValidThumbnail = representative?.media_url && representative?.bbox;
  const representativeId = representative?.representative_id ?? representative?.identity_id ?? null;
  const isPinned = Boolean(representative?.is_pinned);
  const toggleLabel = isPinned ? __('Unpin representative', 'alt-context') : __('Pin representative', 'alt-context');
  const unavailableImageLabel = __('Representative image unavailable', 'alt-context');

  return (
    <div className="acx-identity-cluster__preview">
      {hasValidThumbnail ? (
        <FaceThumbnail
          mediaUrl={representative.media_url!}
          bbox={representative.bbox}
          size="md"
          alt={__('Detected identity thumbnail', 'alt-context')}
          className="acx-identity-cluster__thumb"
        />
      ) : (
        <span
          className="acx-identity-cluster__thumb acx-identity-cluster__thumb--placeholder acx-identity-cluster__thumb--unavailable"
          role="img"
          aria-label={unavailableImageLabel}
        >
          <span className="acx-identity-cluster__thumb-fallback-label">{__('No image', 'alt-context')}</span>
        </span>
      )}
      {memberCount > 1 && <span className="acx-identity-cluster__count">+{memberCount - 1}</span>}
      {representative && representativeId && onTogglePin && (
        <button
          type="button"
          className={`button button-small acx-identity-cluster__pin-toggle${
            isPinned ? ' acx-identity-cluster__pin-toggle--pinned' : ''
          }`}
          onClick={() => onTogglePin(representative, !isPinned)}
          disabled={isPinning}
          aria-label={toggleLabel}
          title={toggleLabel}
        >
          {isPinned ? __('Pinned', 'alt-context') : __('Pin', 'alt-context')}
        </button>
      )}
    </div>
  );
};
