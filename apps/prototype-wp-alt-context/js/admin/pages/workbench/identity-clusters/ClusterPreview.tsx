/**
 * Cluster thumbnail preview with member count badge.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import type { DetectedIdentity, RepresentativeFace } from '../../../api/recognition';
import { Avatar } from '../../../../components/ui/avatar';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { REPRESENTATIVE_VOCABULARY } from './representativeVocabulary';

interface ClusterPreviewProps {
  /** Per-media row or roster representative; cropped when it has a bbox. */
  representative: DetectedIdentity | undefined;
  /** Cluster representative crop; used only when the row has no bbox. */
  representativeFace?: RepresentativeFace | null;
  /** Total number of members in the cluster */
  memberCount: number;
}

/**
 * Displays a face thumbnail with an optional count badge.
 * Per-image cards crop this row; the cluster representative is fallback only.
 * Pin control removed (UXA-07) — mutation/API retained for a deferred relocation.
 */
export const ClusterPreview = ({
  representative,
  representativeFace = representative?.representative_face,
  memberCount,
}: ClusterPreviewProps): React.JSX.Element => {
  // Bbox coordinates belong to that source image; do not mix a row bbox with a representative URL.
  const source = representative?.bbox ? representative : representativeFace;
  const mediaUrl = source?.media_url || source?.attachment_url;
  const bbox = source?.bbox;
  const hasValidThumbnail = Boolean(mediaUrl && bbox);
  const unavailableImageLabel = REPRESENTATIVE_VOCABULARY.imageUnavailable;

  return (
    <div className="acx-identity-cluster__preview">
      {hasValidThumbnail && mediaUrl && bbox ? (
        <FaceThumbnail
          key={mediaUrl}
          mediaUrl={mediaUrl}
          bbox={bbox}
          size="md"
          alt={__('Detected identity thumbnail', 'alt-context')}
          className="acx-identity-cluster__thumb"
        />
      ) : (
        <Avatar
          sizePx={40}
          missingLabel={unavailableImageLabel}
          hideMissingLabel
          className="acx-identity-cluster__thumb acx-identity-cluster__thumb--placeholder"
        />
      )}
      {memberCount > 1 && <span className="acx-identity-cluster__count">+{memberCount - 1}</span>}
    </div>
  );
};
