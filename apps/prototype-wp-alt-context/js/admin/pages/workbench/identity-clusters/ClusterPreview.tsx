/**
 * Cluster thumbnail preview with member count badge.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import type { DetectedIdentity } from '../../../api/recognition';

interface ClusterPreviewProps {
  /** First member to show as representative thumbnail */
  representative: DetectedIdentity | undefined;
  /** Total number of members in the cluster */
  memberCount: number;
}

/**
 * Displays the cluster's representative thumbnail with an optional count badge.
 */
export const ClusterPreview = ({ representative, memberCount }: ClusterPreviewProps): React.JSX.Element => {
  return (
    <div className="acx-identity-cluster__preview">
      {representative?.thumbnail_url ? (
        <img
          src={representative.thumbnail_url}
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
