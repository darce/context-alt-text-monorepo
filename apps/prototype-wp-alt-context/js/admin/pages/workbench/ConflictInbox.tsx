import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ConflictResolutionChoice } from '../../api/recognition';
import { Checkbox } from '../../../components/ui/checkbox';
import { useConflicts } from '../../hooks/useConflicts';
import { useResolveConflict } from '../../hooks/useResolveConflict';
import { useSyncTrigger } from '../../hooks/useSyncTrigger';
import { ConflictDetailPanel } from './conflict-inbox/ConflictDetailPanel';
import { formatEntityLabel, formatTimestamp, getConflictTypeLabel } from './conflict-inbox/conflictInboxUtils';
import { useConflictInboxState } from './conflict-inbox/useConflictInboxState';

const PAGE_SIZE = 20;
const CONFLICT_STATUS = {
  alertRole: 'alert',
  live: 'polite',
  role: 'status',
  testId: 'acx-conflict-inbox-status',
} as const;
const CONFLICT_PENDING_REASON_ID = 'acx-conflict-resolution-pending-reason';
const SYNC_PENDING_REASON_ID = 'acx-conflict-sync-pending-reason';
const NOTICE_VARIANTS = {
  info: 'acx-notice acx-notice--info',
  warning: 'acx-notice acx-notice--warning',
} as const;

export const ConflictInbox = (): React.JSX.Element => {
  const [state, dispatch] = useConflictInboxState();
  const {
    offset,
    selectedConflictIds,
    expandedConflictId,
    pendingResolution,
    pendingBatchResolution,
    showSyncNow,
    resolutionError,
  } = state;

  const conflictsQuery = useConflicts({ resolution_status: 'open', limit: PAGE_SIZE, offset });
  const resolveMutation = useResolveConflict();
  const syncTrigger = useSyncTrigger(false);
  const inboxBusy = conflictsQuery.isLoading || resolveMutation.isPending || syncTrigger.isPending;
  const liveStatus = conflictsQuery.isLoading
    ? __('Loading conflicts…', 'alt-context')
    : resolveMutation.isPending
      ? __('Resolving conflict…', 'alt-context')
      : syncTrigger.isPending
        ? __('Syncing resolved conflicts…', 'alt-context')
        : showSyncNow
          ? __('Conflict resolved. Trigger sync now to converge local state with the backend.', 'alt-context')
          : '';
  const statusRegion = (
    <div
      className="screen-reader-text"
      role={CONFLICT_STATUS.role}
      aria-live={CONFLICT_STATUS.live}
      data-testid={CONFLICT_STATUS.testId}
    >
      {liveStatus}
    </div>
  );

  const handleRequestResolve = async (choice: ConflictResolutionChoice): Promise<void> => {
    if (expandedConflictId === null) {
      return;
    }

    if (pendingResolution?.conflictId !== expandedConflictId || pendingResolution.choice !== choice) {
      dispatch({ type: 'setResolutionError', value: null });
      dispatch({ type: 'setPendingResolution', value: { conflictId: expandedConflictId, choice } });
      return;
    }

    try {
      await resolveMutation.mutateAsync({
        id: expandedConflictId,
        request: { resolution_status: choice },
      });
      dispatch({ type: 'setPendingResolution', value: null });
      dispatch({ type: 'setResolutionError', value: null });
      dispatch({ type: 'setShowSyncNow', value: true });
    } catch {
      dispatch({ type: 'setShowSyncNow', value: false });
      dispatch({
        type: 'setResolutionError',
        value: __('Unable to resolve this conflict. Please try again.', 'alt-context'),
      });
    }
  };

  const handleToggleDetail = (conflictId: number): void => {
    dispatch({ type: 'clearTransientState' });
    dispatch({ type: 'toggleExpandedConflictId', id: conflictId });
  };

  const handleToggleSelection = (conflictId: number): void => {
    dispatch({ type: 'setPendingBatchResolution', value: null });
    dispatch({ type: 'setResolutionError', value: null });
    dispatch({ type: 'toggleSelectedConflictId', id: conflictId });
  };

  if (conflictsQuery.isLoading) {
    return (
      <section aria-label={__('Conflict inbox', 'alt-context')} aria-busy="true">
        {statusRegion}
      </section>
    );
  }

  if (conflictsQuery.isError || !conflictsQuery.data) {
    return (
      <section aria-label={__('Conflict inbox', 'alt-context')}>
        {statusRegion}
        <div className="acx-error-state" role={CONFLICT_STATUS.alertRole}>
          <span aria-hidden="true">⚠</span>
          <p>{__('Unable to load conflicts.', 'alt-context')}</p>
        </div>
      </section>
    );
  }

  const { items, total, limit } = conflictsQuery.data;
  const canPageBack = offset > 0;
  const canPageForward = offset + items.length < total;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = offset + items.length;
  const selectedConflicts = items.filter((conflict) => selectedConflictIds.includes(conflict.id));
  const canSelectAll = items.length > 0;
  const allOnPageSelected = canSelectAll && selectedConflicts.length === items.length;
  const batchAllowedResolutions =
    selectedConflicts.length > 0
      ? selectedConflicts.reduce<ConflictResolutionChoice[]>(
          (allowed, conflict) => allowed.filter((choice) => conflict.allowed_resolutions.includes(choice)),
          ['accepted', 'dismissed', 'accept_backend', 'merge'],
        )
      : [];
  const batchAcceptBackendChoice = batchAllowedResolutions.includes('accepted')
    ? 'accepted'
    : batchAllowedResolutions.includes('accept_backend')
      ? 'accept_backend'
      : null;

  const handleToggleSelectAll = (): void => {
    dispatch({ type: 'setPendingBatchResolution', value: null });
    dispatch({ type: 'setResolutionError', value: null });
    dispatch({
      type: 'setSelectedConflictIds',
      ids: allOnPageSelected ? [] : items.map((conflict) => conflict.id),
    });
  };

  const handleBatchResolve = async (choice: ConflictResolutionChoice): Promise<void> => {
    if (selectedConflicts.length === 0) {
      return;
    }

    if (pendingBatchResolution !== choice) {
      dispatch({ type: 'setResolutionError', value: null });
      dispatch({ type: 'setPendingResolution', value: null });
      dispatch({ type: 'setPendingBatchResolution', value: choice });
      return;
    }

    try {
      for (const conflict of selectedConflicts) {
        await resolveMutation.mutateAsync({
          id: conflict.id,
          request: { resolution_status: choice },
        });
      }
      dispatch({ type: 'setPendingBatchResolution', value: null });
      dispatch({ type: 'setPendingResolution', value: null });
      dispatch({ type: 'setResolutionError', value: null });
      dispatch({ type: 'setSelectedConflictIds', ids: [] });
      dispatch({ type: 'setShowSyncNow', value: true });
    } catch {
      dispatch({ type: 'setShowSyncNow', value: false });
      dispatch({
        type: 'setResolutionError',
        value: __('Unable to resolve the selected conflicts. Please try again.', 'alt-context'),
      });
    }
  };

  const handlePreviousPage = (): void => {
    dispatch({ type: 'setSelectedConflictIds', ids: [] });
    dispatch({ type: 'setPendingBatchResolution', value: null });
    dispatch({ type: 'setOffset', offset: offset - limit });
  };

  const handleNextPage = (): void => {
    dispatch({ type: 'setSelectedConflictIds', ids: [] });
    dispatch({ type: 'setPendingBatchResolution', value: null });
    dispatch({ type: 'setOffset', offset: offset + limit });
  };

  return (
    <section aria-label={__('Conflict inbox', 'alt-context')} aria-busy={inboxBusy ? 'true' : undefined}>
      {statusRegion}
      <h3>{__('Open conflicts', 'alt-context')}</h3>
      <p>{sprintf(__('Showing %1$d-%2$d of %3$d open conflicts.', 'alt-context'), rangeStart, rangeEnd, total)}</p>
      {canSelectAll ? (
        <div className="acx-dashboard__actions">
          <div className="acx-dashboard__actions">
            <Checkbox
              checked={allOnPageSelected}
              onCheckedChange={handleToggleSelectAll}
              ariaLabel={__('Select all conflicts on this page', 'alt-context')}
            />
            <span>{__('Select all conflicts on this page', 'alt-context')}</span>
          </div>
          {selectedConflicts.length > 0 ? (
            <span>{sprintf(__('%d selected', 'alt-context'), selectedConflicts.length)}</span>
          ) : null}
          {batchAcceptBackendChoice ? (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                void handleBatchResolve(batchAcceptBackendChoice);
              }}
              disabled={resolveMutation.isPending}
              aria-disabled={resolveMutation.isPending ? true : undefined}
              aria-describedby={resolveMutation.isPending ? CONFLICT_PENDING_REASON_ID : undefined}
            >
              {pendingBatchResolution === batchAcceptBackendChoice
                ? __('Confirm accept backend selected', 'alt-context')
                : __('Accept backend for selected', 'alt-context')}
            </button>
          ) : null}
          {batchAllowedResolutions.includes('dismissed') ? (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                void handleBatchResolve('dismissed');
              }}
              disabled={resolveMutation.isPending}
              aria-disabled={resolveMutation.isPending ? true : undefined}
              aria-describedby={resolveMutation.isPending ? CONFLICT_PENDING_REASON_ID : undefined}
            >
              {pendingBatchResolution === 'dismissed'
                ? __('Confirm keep local for selected', 'alt-context')
                : __('Keep local for selected', 'alt-context')}
            </button>
          ) : null}
          {batchAllowedResolutions.includes('merge') ? (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                void handleBatchResolve('merge');
              }}
              disabled={resolveMutation.isPending}
              aria-disabled={resolveMutation.isPending ? true : undefined}
              aria-describedby={resolveMutation.isPending ? CONFLICT_PENDING_REASON_ID : undefined}
            >
              {pendingBatchResolution === 'merge'
                ? __('Confirm merge selected', 'alt-context')
                : __('Merge selected', 'alt-context')}
            </button>
          ) : null}
        </div>
      ) : null}
      {showSyncNow || syncTrigger.isPending ? (
        <div className={NOTICE_VARIANTS.info}>
          <span aria-hidden="true">ℹ</span>
          <p>{__('Conflict resolved. Trigger sync now to converge local state with the backend.', 'alt-context')}</p>
          <button
            type="button"
            className="button button-primary"
            onClick={() => syncTrigger.mutate()}
            disabled={syncTrigger.isPending}
            aria-disabled={syncTrigger.isPending ? true : undefined}
            aria-describedby={syncTrigger.isPending ? SYNC_PENDING_REASON_ID : undefined}
          >
            {__('Sync now', 'alt-context')}
          </button>
        </div>
      ) : null}
      {resolutionError ? (
        <div className={NOTICE_VARIANTS.warning} role={CONFLICT_STATUS.alertRole}>
          <span aria-hidden="true">⚠</span>
          <p>{resolutionError}</p>
        </div>
      ) : null}
      {resolveMutation.isPending ? (
        <p id={CONFLICT_PENDING_REASON_ID}>{__('Conflict resolution in progress. Please wait.', 'alt-context')}</p>
      ) : null}
      {syncTrigger.isPending ? (
        <p id={SYNC_PENDING_REASON_ID}>{__('Sync in progress. Please wait.', 'alt-context')}</p>
      ) : null}
      {items.length === 0 ? (
        <p>{__('No open conflicts.', 'alt-context')}</p>
      ) : (
        <>
          <ul className="acx-dashboard__activity-list">
            {items.map((conflict) => {
              const isExpanded = expandedConflictId === conflict.id;

              return (
                <li key={conflict.id} className="acx-dashboard__activity-item">
                  <div>
                    <div className="acx-dashboard__actions">
                      <Checkbox
                        checked={selectedConflictIds.includes(conflict.id)}
                        onCheckedChange={() => handleToggleSelection(conflict.id)}
                        ariaLabel={__('Select conflict', 'alt-context')}
                      />
                      <span>{__('Select conflict', 'alt-context')}</span>
                    </div>
                    <strong>{formatEntityLabel(conflict)}</strong>
                    <p>{sprintf(__('Type: %s', 'alt-context'), getConflictTypeLabel(conflict))}</p>
                    <p>{conflict.conflict_code}</p>
                    <p>{formatTimestamp(conflict.created_at)}</p>
                  </div>
                  <button
                    type="button"
                    className="button button-link"
                    onClick={() => handleToggleDetail(conflict.id)}
                    aria-expanded={isExpanded}
                  >
                    {isExpanded ? __('Hide detail', 'alt-context') : __('Review conflict', 'alt-context')}
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="acx-dashboard__actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={handlePreviousPage}
              disabled={!canPageBack}
            >
              {__('Previous', 'alt-context')}
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={handleNextPage}
              disabled={!canPageForward}
            >
              {__('Next', 'alt-context')}
            </button>
          </div>
        </>
      )}
      <ConflictDetailPanel
        conflictId={expandedConflictId}
        pendingChoice={pendingResolution?.conflictId === expandedConflictId ? pendingResolution.choice : null}
        onRequestResolve={(choice) => {
          void handleRequestResolve(choice);
        }}
        isResolving={resolveMutation.isPending}
        disabledReasonId={resolveMutation.isPending ? CONFLICT_PENDING_REASON_ID : undefined}
      />
    </section>
  );
};
