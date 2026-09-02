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
import { EmptyState, EmptyStateVariant } from '../../../components/ui/EmptyState';
import { toWorkbench } from '../../../navigation/appLinks';
import { EmptyStateWarning } from './EmptyStateWarning';
import { pendingMergeTwinForCluster } from './pendingMergeTwin';
import { groupIdentitiesByClusters } from './utils';
import { IdentityClusterItem } from './IdentityClusterItem';
import { useInlineSuggestionBatch } from './useInlineSuggestionBatch';
import { useSuggestionReviewData } from './useSuggestionReviewData';

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
  const { mergeSuggestions, scheduleAcceptMerge, scheduleRejectMerge, isCardPending } =
    useSuggestionReviewData();

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

    // BR-05: a reachable-but-erroring backend (endpoint_error) is a distinct
    // honest state from offline (unavailable) — say so instead of falling through
    // to a confident "none detected".
    if (dataSource === DATA_SOURCE.ENDPOINT_ERROR) {
      return (
        <EmptyStateWarning
          title={__('Identity data unavailable', 'alt-context')}
          message={__('Recognition is reachable but returned an error. Please retry.', 'alt-context')}
          onRetry={onRetry}
        />
      );
    }

    // BR-09: an empty local projection for this item is ambiguous between
    // "analyzed, none found" and "not yet analyzed". The offline projection
    // cannot assert a final scan result, so present it as pending sync rather
    // than a confident "none detected". Only a backend_proxy (or unknown) empty
    // result — where recognition was actually reached — is a confident "none".
    if (dataSource === DATA_SOURCE.LOCAL_PROJECTION) {
      return (
        <p className="acx-identity-clusters__empty">
          {__('No identities synced for this item yet.', 'alt-context')}
        </p>
      );
    }

    return (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading={__('No identities detected yet.', 'alt-context')}
        body={__('Scan media to find faces in this item.', 'alt-context')}
        action={{ label: __('Go to Scan', 'alt-context'), href: toWorkbench({ tab: 'scan' }) }}
        headingLevel={3}
        announceState={false}
      />
    );
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
      {clusters.map((cluster) => {
        const twin = pendingMergeTwinForCluster(cluster.clusterId, mergeSuggestions);
        const twinPending = twin
          ? isCardPending(twin.suggestionId, ['acceptMerge', 'rejectMerge'])
          : false;
        return (
          <IdentityClusterItem
            key={cluster.key}
            cluster={cluster}
            canLabel
            canMutate={canMutate}
            inlineSuggestionMatch={getMatch(cluster.members[0]?.identity_id)}
            mergeTwin={
              twin
                ? {
                    suggestionId: twin.suggestionId,
                    survivorLabel: twin.survivorLabel,
                    onAccept: () => {
                      void scheduleAcceptMerge(twin.suggestionId);
                    },
                    onReject: () => {
                      void scheduleRejectMerge(twin.suggestionId);
                    },
                    isPending: twinPending,
                    disabledReason: twinPending
                      ? __('Saving merge suggestion…', 'alt-context')
                      : null,
                  }
                : undefined
            }
          />
        );
      })}
    </div>
  );
};
