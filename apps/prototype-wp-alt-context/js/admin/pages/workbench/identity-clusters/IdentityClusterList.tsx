/**
 * List of identity clusters for a media item.
 *
 * This is the main entry point component that groups identities by cluster
 * and renders each cluster as an editable item.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { DATA_SOURCE, type DataSource } from '../../../api/recognition/types';
import { type DetectedIdentity } from '../../../api/recognition';
import { EmptyState, EmptyStateVariant } from '../../../components/ui/EmptyState';
import { APP_LINK_VALUES, toWorkbench } from '../../../navigation/appLinks';
import { ClusterActions } from './ClusterActions';
import { ClusterPreview } from './ClusterPreview';
import { EmptyStateWarning } from './EmptyStateWarning';
import { InlineSuggestionPrompt } from './InlineSuggestionPrompt';
import { pendingMergeTwinForCluster } from './pendingMergeTwin';
import { isMeaningfulMergeLabel } from './resolveMergeSurvivor';
import { TWIN_CHIP_PENDING_STATUS } from './twinChipCopy';
import { groupIdentitiesByClusters, isUngroupedGroup, unlabeledSuggestionBatchIds } from './utils';
import { IdentityClusterItem } from './IdentityClusterItem';
import { useClusterMutations } from './useClusterMutations';
import { useInlineSuggestionBatch, type InlineSuggestionBatchResult } from './useInlineSuggestionBatch';
import { usePendingMergeTwins } from './usePendingMergeTwins';

interface IdentityClusterListProps {
  /** Detected identities to display */
  identities: DetectedIdentity[];
  dataSource?: DataSource;
  onRetry?: () => void;
}

interface UngroupedResidueSectionProps {
  members: DetectedIdentity[];
  canMutate: boolean;
  getMatch: InlineSuggestionBatchResult['getMatch'];
}

const UngroupedResidueSection = ({
  members,
  canMutate,
  getMatch,
}: UngroupedResidueSectionProps): React.JSX.Element => {
  const headingId = React.useId();
  const heading = sprintf(__('Not yet grouped (%d)', 'alt-context'), members.length);
  const mutations = useClusterMutations({
    clusterId: null,
    identityCount: 1,
    currentLabel: null,
    derivedLabel: null,
  });

  return (
    <section className="acx-identity-clusters__ungrouped" aria-labelledby={headingId}>
      <h3 id={headingId} className="acx-identity-clusters__ungrouped-heading">
        {heading}
      </h3>
      <ul className="acx-identity-clusters__ungrouped-faces">
        {members.map((member) => (
          <li key={member.identity_id} className="acx-identity-clusters__ungrouped-face">
            <ClusterPreview
              representative={member}
              representativeFace={member.representative_face}
              memberCount={1}
            />
            {!member.clustering_pending && (
              <ClusterActions
                canEdit={false}
                canSearchForMatch
                hasLabel={false}
                isAutoLabel={false}
                canSplit={false}
                canReject={false}
                isPending={mutations.isPending}
                // WHY: residue is not a person card; Find similar is the singleton
                // affordance (R-03) without opening an Unnamed person editor.
                onEdit={() => undefined}
                onWrongPerson={() => undefined}
                onSplit={() => undefined}
              />
            )}
            {canMutate ? (
              <InlineSuggestionPrompt
                match={getMatch(member.identity_id)}
                onConfirm={(clusterId, _label, suggestionId) => {
                  mutations.assignToCluster(member.identity_id, clusterId, undefined, suggestionId);
                }}
                onReject={() => undefined}
                isPending={mutations.isPending}
              />
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
};

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
  const identityGroups = React.useMemo(
    () => clusters.filter((cluster) => !isUngroupedGroup(cluster)),
    [clusters],
  );
  const ungroupedGroup = React.useMemo(
    () => clusters.find((cluster) => isUngroupedGroup(cluster)),
    [clusters],
  );
  const isLabelOnly = dataSource === DATA_SOURCE.BACKEND_PROXY;
  const canMutate = !isLabelOnly;
  const { mergeSuggestions, truncated, scheduleAcceptMerge, scheduleRejectMerge, isCardPending } =
    usePendingMergeTwins();

  // Same unlabeled predicate as IdentityClusterItem's prompt gate, plus every
  // residue member: grouping changes presentation only, never the batch (rg-002).
  const batchIdentityIds = React.useMemo(() => {
    if (!canMutate) {
      return [];
    }
    return unlabeledSuggestionBatchIds(clusters);
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
      {identityGroups.map((cluster) => {
        const twin = canMutate
          ? pendingMergeTwinForCluster(cluster.clusterId, mergeSuggestions)
          : null;
        const twinPending = twin
          ? isCardPending(twin.suggestionId, ['acceptMerge', 'rejectMerge'])
          : false;
        const showTruncatedReviewLink =
          truncated &&
          canMutate &&
          twin == null &&
          !isMeaningfulMergeLabel(cluster.label);
        return (
          <React.Fragment key={cluster.key}>
            <IdentityClusterItem
              cluster={cluster}
              canLabel
              canMutate={canMutate}
              inlineSuggestionMatch={getMatch(cluster.members[0]?.identity_id)}
              mergeTwin={
                twin
                  ? {
                      suggestionId: twin.suggestionId,
                      survivorClusterId: twin.survivorClusterId,
                      survivorLabel: twin.survivorLabel,
                      survivorMediaUrl: twin.survivorMediaUrl,
                      survivorBbox: twin.survivorBbox,
                      onAccept: () => {
                        void scheduleAcceptMerge(twin.suggestionId);
                      },
                      onReject: () => {
                        void scheduleRejectMerge(twin.suggestionId);
                      },
                      isPending: twinPending,
                      disabledReason: twinPending ? TWIN_CHIP_PENDING_STATUS : null,
                    }
                  : undefined
              }
            />
            {showTruncatedReviewLink ? (
              <a
                className="acx-identity-clusters__truncated-review"
                href={toWorkbench({ tab: 'scan', panel: APP_LINK_VALUES.panelReview })}
              >
                {__('Review pending merges', 'alt-context')}
              </a>
            ) : null}
          </React.Fragment>
        );
      })}
      {ungroupedGroup ? (
        <UngroupedResidueSection members={ungroupedGroup.members} canMutate={canMutate} getMatch={getMatch} />
      ) : null}
    </div>
  );
};
