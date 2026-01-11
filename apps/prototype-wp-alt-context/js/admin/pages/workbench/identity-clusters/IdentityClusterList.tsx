/**
 * List of identity clusters for a media item.
 *
 * This is the main entry point component that groups identities by cluster
 * and renders each cluster as an editable item.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import { type DetectedIdentity } from '../../../api/recognition';
import { getConfig } from '../../../api/config';
import { useClusterEvents } from '../../../hooks/useClusterEvents';
import { groupIdentitiesByClusters } from './utils';
import { IdentityClusterItem } from './IdentityClusterItem';
import { CurateTopClustersPrompt } from './CurateTopClustersPrompt';

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
 */
export const IdentityClusterList = ({ identities }: IdentityClusterListProps): React.JSX.Element => {
  const config = getConfig();
  const clusters = React.useMemo(() => groupIdentitiesByClusters(identities), [identities]);

  // Subscribe to real-time cluster notifications
  useClusterEvents(config.tenant_id ?? '');

  if (clusters.length === 0) {
    return <p className="acx-identity-clusters__empty">{__('No identities detected yet.', 'alt-context')}</p>;
  }

  // Find if any clusters in this media are unlabeled
  const hasUnlabeled = clusters.some((c) => !c.label || c.label.startsWith('cluster-'));

  return (
    <div className="acx-identity-clusters">
      {hasUnlabeled && <CurateTopClustersPrompt tenantId={config.tenant_id ?? ''} />}
      {clusters.map((cluster) => (
        <IdentityClusterItem key={cluster.key} cluster={cluster} />
      ))}
    </div>
  );
};
