/**
 * Cluster thumbnail preview with member count badge.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import type { DetectedIdentity } from '../../../api/recognition';
import { DurableFaceThumb } from '../../../../components/ui/DurableFaceThumb';

interface ClusterPreviewProps {
  /** First member to show as representative thumbnail */
  representative: DetectedIdentity | undefined;
  /** Total number of members in the cluster */
  memberCount: number;
}

/**
 * Displays the cluster's representative thumbnail with an optional count badge.
 * The thumbnail shows the face cropped from the original image using InsightFace bbox.
 * Pin control removed (UXA-07) — mutation/API retained for a deferred relocation.
 */
export const ClusterPreview = ({ representative, memberCount }: ClusterPreviewProps): React.JSX.Element => {
  return (
    <div className="acx-identity-cluster__preview">
      <DurableFaceThumb
        source={{
          thumbUrl: representative?.thumb_url,
          attachmentUrl: representative?.attachment_url,
          mediaUrl: representative?.media_url,
          bbox: representative?.bbox,
        }}
        size="md"
        alt={__('Detected identity thumbnail', 'alt-context')}
        className="acx-identity-cluster__thumb"
      />
      {memberCount > 1 && <span className="acx-identity-cluster__count">+{memberCount - 1}</span>}
    </div>
  );
};
