import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { Checkbox } from '../../../components/ui/checkbox';
import type { ClusterSummary } from '../../api/recognition';
import { useClusterSelection } from '../../hooks/useClusterSelection';
import { BulkActionBar } from './BulkActionBar';
import { ConfirmDialog } from './ConfirmDialog';
import type { useClusterActions } from './hooks/useClusterActions';
import { isUnlabeledCluster, workbenchReviewQueueUrl } from './rosterRoute';
import { useRosterBulkConfirmation } from './useRosterBulkConfirmation';

interface NeedsAssignmentSectionProps {
  clusters: ClusterSummary[];
  selection: ReturnType<typeof useClusterSelection>;
  actions: ReturnType<typeof useClusterActions>;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onOpenCluster: (cluster: ClusterSummary) => void;
  truncated?: boolean;
  listTotal?: number;
}

const ZERO_STATE_REASON = __('No unlabeled clusters need assignment', 'alt-context');

export const NeedsAssignmentSection = ({
  clusters,
  selection,
  actions,
  isLoading,
  isError,
  onRetry,
  onOpenCluster,
  truncated = false,
  listTotal,
}: NeedsAssignmentSectionProps): React.JSX.Element => {
  const unlabeled = React.useMemo(() => clusters.filter(isUnlabeledCluster), [clusters]);
  const unlabeledIds = React.useMemo(() => unlabeled.map((cluster) => cluster.id), [unlabeled]);
  const hasUnlabeled = unlabeled.length > 0;
  const controlsDisabled = !hasUnlabeled || isLoading || isError;

  // Rail bulk ops must never act on labeled ids selected elsewhere on the page.
  // Scope count + merge/dismiss inputs to selection ∩ unlabeledIds.
  const railSelectedIds = React.useMemo(() => {
    const unlabeledSet = new Set(unlabeledIds);
    const scoped = new Set<string>();
    selection.selectedIds.forEach((id) => {
      if (unlabeledSet.has(id)) {
        scoped.add(id);
      }
    });
    return scoped;
  }, [selection.selectedIds, unlabeledIds]);

  const railSelection = React.useMemo(
    () => ({
      selectedIds: railSelectedIds,
      count: railSelectedIds.size,
    }),
    [railSelectedIds],
  );

  const {
    confirmAction,
    setConfirmAction,
    handleBulkMerge,
    handleBulkDismiss,
    handleConfirm,
    handleConfirmOpenChange,
    confirmDialogCopy,
  } = useRosterBulkConfirmation({
    selection: railSelection,
    bulkMergeMutation: actions.bulkMergeMutation,
    bulkDismissMutation: actions.bulkDismissMutation,
  });

  const handleRetryMerge = React.useCallback(() => {
    const remaining = actions.bulkMergeFailure?.remainingClusterIds;
    if (!remaining || remaining.length < 2) {
      return;
    }
    actions.clearBulkMergeFailure();
    selection.selectAll(remaining);
    void actions.bulkMergeMutation.mutateAsync({ clusterIds: remaining });
  }, [actions, selection]);

  const selectedVisibleCount = railSelection.count;

  const selectAllState = selection.isAllSelected(unlabeledIds)
    ? true
    : selectedVisibleCount > 0
      ? 'indeterminate'
      : false;

  const handleSelectAll = React.useCallback(() => {
    if (!hasUnlabeled) {
      return;
    }
    if (selection.isAllSelected(unlabeledIds)) {
      selection.clear();
      return;
    }
    selection.selectAll(unlabeledIds);
  }, [hasUnlabeled, unlabeledIds, selection]);

  const handleClearRailSelection = React.useCallback(() => {
    // Drop only rail-owned ids so foreign (labeled) selections outside the rail stay intact.
    const remaining = Array.from(selection.selectedIds).filter((id) => !railSelectedIds.has(id));
    if (remaining.length === 0) {
      selection.clear();
      return;
    }
    selection.selectAll(remaining);
  }, [railSelectedIds, selection]);

  return (
    <section
      className="acx-needs-assignment"
      aria-labelledby="acx-needs-assignment-title"
      data-testid="needs-assignment-section"
    >
      <header className="acx-needs-assignment__header">
        <div className="acx-needs-assignment__title-row">
          <Checkbox
            checked={hasUnlabeled ? selectAllState : false}
            onCheckedChange={handleSelectAll}
            ariaLabel={__('Select all unlabeled clusters', 'alt-context')}
            disabled={controlsDisabled}
          />
          <h2 id="acx-needs-assignment-title" className="acx-needs-assignment__title">
            {__('Needs assignment', 'alt-context')}
          </h2>
          <span className="acx-needs-assignment__count" data-testid="needs-assignment-count">
            {isLoading
              ? __('Loading…', 'alt-context')
              : sprintf(
                  // translators: %d: unlabeled cluster count
                  __('%d unlabeled', 'alt-context'),
                  unlabeled.length,
                )}
          </span>
        </div>
        {railSelection.count > 0 || controlsDisabled ? (
          <BulkActionBar
            count={railSelection.count}
            onMerge={handleBulkMerge}
            onDismiss={handleBulkDismiss}
            onClear={handleClearRailSelection}
            isMerging={actions.bulkMergeMutation.isPending}
            isDismissing={actions.bulkDismissMutation.isPending}
            mergeProgress={actions.bulkMergeProgress}
            mergeFailure={actions.bulkMergeFailure}
            onRetryMerge={handleRetryMerge}
            onDismissFailure={actions.clearBulkMergeFailure}
            controlsDisabled={controlsDisabled && railSelection.count === 0}
            controlsDisabledReason={ZERO_STATE_REASON}
          />
        ) : null}
      </header>

      {isError ? (
        <div className="acx-needs-assignment__error" role="alert">
          <p>{__('Unable to load clusters for assignment.', 'alt-context')}</p>
          <button type="button" className="acx-button acx-button--secondary" onClick={onRetry}>
            {__('Retry', 'alt-context')}
          </button>
        </div>
      ) : null}

      {!isLoading && !isError && !hasUnlabeled ? (
        <p className="acx-needs-assignment__zero" role="status" data-testid="needs-assignment-zero">
          {ZERO_STATE_REASON}
          {'. '}
          <a href={workbenchReviewQueueUrl()}>{__('Open review queue', 'alt-context')}</a>
        </p>
      ) : null}

      {truncated && listTotal != null ? (
        <p className="acx-needs-assignment__truncated" role="status">
          {sprintf(
            __('Showing %d of %d clusters. Refine the list to review the remaining matches.', 'alt-context'),
            clusters.length,
            listTotal,
          )}
        </p>
      ) : null}

      {hasUnlabeled ? (
        <ul className="acx-needs-assignment__list" data-testid="needs-assignment-list">
          {unlabeled.map((cluster) => {
            const shortId = cluster.id.slice(0, 8);
            const title = sprintf(__('Cluster %s', 'alt-context'), shortId);
            const selected = selection.isSelected(cluster.id);
            return (
              <li key={cluster.id} className="acx-needs-assignment__item">
                <Checkbox
                  checked={selected}
                  onCheckedChange={() => selection.toggle(cluster.id)}
                  ariaLabel={sprintf(__('Select cluster %s', 'alt-context'), shortId)}
                />
                <button
                  type="button"
                  className="acx-needs-assignment__open"
                  onClick={() => onOpenCluster(cluster)}
                >
                  {title}
                  <span className="acx-needs-assignment__meta">
                    {sprintf(
                      // translators: %d: identity count
                      __('%d identities', 'alt-context'),
                      cluster.identity_count,
                    )}
                  </span>
                </button>
                <a
                  className="acx-needs-assignment__workbench-link"
                  href={workbenchReviewQueueUrl({ clusterId: cluster.id })}
                >
                  {__('Review in workbench', 'alt-context')}
                </a>
              </li>
            );
          })}
        </ul>
      ) : null}

      {confirmDialogCopy ? (
        <ConfirmDialog
          open={confirmAction !== null}
          onOpenChange={handleConfirmOpenChange}
          onConfirm={handleConfirm}
          onCancel={() => setConfirmAction(null)}
          title={confirmDialogCopy.title}
          description={confirmDialogCopy.description}
          confirmLabel={confirmDialogCopy.confirmLabel}
          isPending={actions.bulkMergeMutation.isPending || actions.bulkDismissMutation.isPending}
        />
      ) : null}
    </section>
  );
};
