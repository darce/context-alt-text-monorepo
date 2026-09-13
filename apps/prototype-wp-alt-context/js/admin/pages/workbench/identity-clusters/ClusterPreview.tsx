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
  /** Member used when the reference crop is unavailable. */
  representative: DetectedIdentity | undefined;
  representativeFace?: RepresentativeFace | null;
  /** Total number of members in the cluster */
  memberCount: number;
}

/**
 * Displays the cluster's representative thumbnail with an optional count badge.
 * The thumbnail shows the face cropped from the original image using InsightFace bbox.
 * Pin control removed (UXA-07) — mutation/API retained for a deferred relocation.
 */
export const ClusterPreview = ({ representative, representativeFace = representative?.representative_face, memberCount }: ClusterPreviewProps): React.JSX.Element => {
  // Select the source as a unit: bbox coordinates belong to that source image.
  const referenceUrl = representativeFace?.media_url || representativeFace?.attachment_url;
  const source = referenceUrl && representativeFace?.bbox ? representativeFace : representative;
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
