/**
 * List of identity clusters for a media item.
 *
 * This is the main entry point component that groups identities by cluster
 * and renders each cluster as an editable item.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import { type DetectedIdentity } from '../../../api/recognition';
import { groupIdentitiesByClusters } from './utils';
import { IdentityClusterItem } from './IdentityClusterItem';

interface IdentityClusterListProps {
  /** Detected identities to display */
  identities: DetectedIdentity[];
}

/**
 * Groups identities by cluster and renders them as a list of editable items.
 *
 * Each cluster shows:
 * - Representative thumbnail with member count
 * - Label (editable via Combobox with suggestions)
 * - Actions: Edit, Wrong person, Split
 *
 * NOTE: v4.12.0 - CurateTopClustersPrompt removed; naming queue is now in
 * SuggestionReviewPanel for unified curation flow.
 */
export const IdentityClusterList = ({ identities }: IdentityClusterListProps): React.JSX.Element => {
  const clusters = React.useMemo(() => groupIdentitiesByClusters(identities), [identities]);

  if (clusters.length === 0) {
    return <p className="acx-identity-clusters__empty">{__('No identities detected yet.', 'alt-context')}</p>;
  }

  return (
    <div className="acx-identity-clusters">
      {clusters.map((cluster) => (
        <IdentityClusterItem key={cluster.key} cluster={cluster} />
      ))}
    </div>
  );
};
