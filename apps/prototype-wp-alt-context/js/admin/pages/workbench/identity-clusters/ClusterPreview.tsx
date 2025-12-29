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
}

/**
 * Displays the cluster's representative thumbnail with an optional count badge.
 * The thumbnail shows the face cropped from the original image using InsightFace bbox.
 */
export const ClusterPreview = ({ representative, memberCount }: ClusterPreviewProps): React.JSX.Element => {
  const hasValidThumbnail = representative?.media_url && representative?.bbox;

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
        <span className="acx-identity-cluster__thumb acx-identity-cluster__thumb--placeholder" />
      )}
      {memberCount > 1 && <span className="acx-identity-cluster__count">+{memberCount - 1}</span>}
    </div>
  );
};
