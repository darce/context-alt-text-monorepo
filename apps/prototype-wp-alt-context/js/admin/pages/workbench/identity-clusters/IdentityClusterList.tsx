/**
 * List of identity clusters for a media item.
 *
 * This is the main entry point component that groups identities by cluster
 * and renders each cluster as an editable item.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import { DATA_SOURCE, type DataSource } from '../../../api/recognition/types';
import { type DetectedIdentity } from '../../../api/recognition';
import { EmptyStateWarning } from './EmptyStateWarning';
import { groupIdentitiesByClusters } from './utils';
import { IdentityClusterItem } from './IdentityClusterItem';
import { useInlineSuggestionBatch } from './useInlineSuggestionBatch';

interface IdentityClusterListProps {
  /** Detected identities to display */
  identities: DetectedIdentity[];
  dataSource?: DataSource;
  onRetry?: () => void;
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
 * ReviewQueue for unified curation flow.
 */
export const IdentityClusterList = ({
  identities,
  dataSource,
  onRetry,
}: IdentityClusterListProps): React.JSX.Element => {
  const clusters = React.useMemo(() => groupIdentitiesByClusters(identities), [identities]);
  const isLabelOnly = dataSource === DATA_SOURCE.BACKEND_PROXY;
  const canMutate = !isLabelOnly;

  // Same predicate as IdentityClusterItem's render gate:
  // `!cluster.label && anchorIdentityId && canMutate`, with anchorIdentityId
  // derived from the shared grouped data (members[0]). Label-only mode yields
  // an empty set, so the batch fetches nothing.
  const batchIdentityIds = React.useMemo(() => {
    if (!canMutate) {
      return [];
    }
    return clusters
      .filter((cluster) => !cluster.label)
      .map((cluster) => cluster.members[0]?.identity_id)
      .filter((identityId): identityId is string => Boolean(identityId));
  }, [clusters, canMutate]);

  const { getMatch } = useInlineSuggestionBatch(batchIdentityIds);

  if (clusters.length === 0) {
    if (dataSource === DATA_SOURCE.UNAVAILABLE) {
      return (
        <EmptyStateWarning
          title={__('Identity data unavailable', 'alt-context')}
          message={__('We could not load identities for this media item right now.', 'alt-context')}
          onRetry={onRetry}
        />
      );
    }

    return <p className="acx-identity-clusters__empty">{__('No identities detected yet.', 'alt-context')}</p>;
  }

  return (
    <div className="acx-identity-clusters">
      {isLabelOnly && (
        <p className="acx-identity-clusters__notice">
          {__(
            'Names can be curated now. Split/remove actions stay disabled until local sync completes.',
            'alt-context',
          )}
        </p>
      )}
      {clusters.map((cluster) => (
        <IdentityClusterItem
          key={cluster.key}
          cluster={cluster}
          canLabel
          canMutate={canMutate}
          inlineSuggestionMatch={getMatch(cluster.members[0]?.identity_id)}
        />
      ))}
    </div>
  );
};
