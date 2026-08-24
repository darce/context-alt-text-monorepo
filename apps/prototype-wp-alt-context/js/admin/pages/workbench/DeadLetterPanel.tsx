import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { OutboxOperation } from '../../api/recognition';
import { useBulkRetryOperations } from '../../hooks/useBulkRetryOperations';
import { useDeadLetterOperations } from '../../hooks/useDeadLetterOperations';
import { useDiscardOperation } from '../../hooks/useDiscardOperation';
import { useOutboxOperations } from '../../hooks/useOutboxOperations';
import { useRetryOperation } from '../../hooks/useRetryOperation';
import { useSyncStatus } from '../../hooks/useSyncStatus';
import { SYNC_VOCABULARY } from './syncVocabulary';

const PAGE_SIZE = 20;
const TIMELINE_PAGE_SIZE = 10;
const BULK_RETRY_ARM_TIMEOUT_MS = 8000;
const DEAD_LETTER_STATUS = {
  alertRole: 'alert',
  live: 'polite',
  role: 'status',
  testId: 'acx-dead-letter-status',
} as const;
const DEAD_LETTER_PENDING_REASON_ID = 'acx-dead-letter-pending-reason';
const NOTICE_VARIANTS = {
  info: 'acx-notice acx-notice--info',
  warning: 'acx-notice acx-notice--warning',
} as const;
const TIMELINE_STATUSES = ['all', 'pending', 'acknowledged', 'conflict', 'failed', 'discarded'] as const;
type TimelineStatusFilter = (typeof TIMELINE_STATUSES)[number];

const OPERATION_LABELS: Record<string, string> = {
  cluster_label_updated: __('Cluster label update', 'alt-context'),
  cluster_dismissed: __('Cluster dismiss', 'alt-context'),
  cluster_undismissed: __('Cluster undismiss', 'alt-context'),
  identity_reassigned: __('Identity reassignment', 'alt-context'),
  cluster_person_bound: __('Cluster person bind', 'alt-context'),
  cluster_person_unbound: __('Cluster person unbind', 'alt-context'),
  person_created: __('Person created', 'alt-context'),
  person_updated: __('Person updated', 'alt-context'),
  person_deleted: __('Person deleted', 'alt-context'),
  cluster_merged: __('Cluster merge', 'alt-context'),
  revert_merge_cluster: __('Cluster merge revert', 'alt-context'),
  assign_outlier_to_cluster: __('Assign outlier to cluster', 'alt-context'),
  cluster_created_for_identity: __('Create cluster for identity', 'alt-context'),
};

interface DeadLetterPanelState {
  offset: number;
  timelineOffset: number;
  timelineStatus: TimelineStatusFilter;
  pendingDiscardId: number | null;
  bulkRetryArmed: boolean;
  actionStatus: string;
  notice: string | null;
  mutationError: string | null;
}

type DeadLetterPanelAction =
  | { type: 'setOffset'; offset: number }
  | { type: 'setTimelineOffset'; offset: number }
  | { type: 'setTimelineStatus'; status: TimelineStatusFilter }
  | { type: 'setPendingDiscardId'; id: number | null }
  | { type: 'setBulkRetryArmed'; armed: boolean }
  | { type: 'setActionStatus'; status: string }
  | { type: 'setNotice'; notice: string | null }
  | { type: 'setMutationError'; error: string | null };

const INITIAL_STATE: DeadLetterPanelState = {
  offset: 0,
  timelineOffset: 0,
  timelineStatus: 'all',
  pendingDiscardId: null,
  bulkRetryArmed: false,
  actionStatus: '',
  notice: null,
  mutationError: null,
};

const deadLetterPanelReducer = (state: DeadLetterPanelState, action: DeadLetterPanelAction): DeadLetterPanelState => {
  switch (action.type) {
    case 'setOffset':
      return { ...state, offset: action.offset };
    case 'setTimelineOffset':
      return { ...state, timelineOffset: action.offset };
    case 'setTimelineStatus':
      return { ...state, timelineStatus: action.status };
    case 'setPendingDiscardId':
      return { ...state, pendingDiscardId: action.id };
    case 'setBulkRetryArmed':
      return state.bulkRetryArmed === action.armed ? state : { ...state, bulkRetryArmed: action.armed };
    case 'setActionStatus':
      return { ...state, actionStatus: action.status };
    case 'setNotice':
      return { ...state, notice: action.notice };
    case 'setMutationError':
      return { ...state, mutationError: action.error };
    default:
      return state;
  }
};

const formatOperationType = (operationType: string): string =>
  OPERATION_LABELS[operationType] ?? operationType.replaceAll('_', ' ');

const formatStatusLabel = (status: string): string => status.replaceAll('_', ' ');

const formatOperationIdentity = (operation: OutboxOperation): string =>
  sprintf(
    __('%1$s for %2$s (operation %3$d)', 'alt-context'),
    formatOperationType(operation.operation_type),
    operation.entity_key,
    operation.id,
  );

const formatTimestamp = (value: string | null | undefined): string => {
  if (!value) {
    return __('Unknown time', 'alt-context');
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
};

const formatErrorSummary = (operation: OutboxOperation): string => {
  if (operation.last_error_code && operation.last_error_message) {
    return `${operation.last_error_code}: ${operation.last_error_message}`;
  }

  if (operation.last_error_message) {
    return operation.last_error_message;
  }

  if (operation.last_error_code) {
    return operation.last_error_code;
  }

  return __('No error details recorded.', 'alt-context');
};

const formatPayloadSummary = (payload: Record<string, unknown> | undefined): string | null => {
  if (!payload || Object.keys(payload).length === 0) {
    return null;
  }

  if (typeof payload.label === 'string') {
    return sprintf(__('Payload label: %s', 'alt-context'), payload.label);
  }

  if (typeof payload.person_id === 'string') {
    return sprintf(__('Payload person: %s', 'alt-context'), payload.person_id);
  }

  return JSON.stringify(payload);
};

export const DeadLetterPanel = (): React.JSX.Element => {
  const [state, dispatch] = React.useReducer(deadLetterPanelReducer, INITIAL_STATE);
  const [loadingAnnouncement, setLoadingAnnouncement] = React.useState('');
  const {
    offset,
    timelineOffset,
    timelineStatus,
    pendingDiscardId,
    bulkRetryArmed,
    actionStatus,
    notice,
    mutationError,
  } = state;

  const operationsQuery = useDeadLetterOperations({ limit: PAGE_SIZE, offset });
  const timelineQuery = useOutboxOperations({
    limit: TIMELINE_PAGE_SIZE,
    offset: timelineOffset,
    status: timelineStatus === 'all' ? undefined : timelineStatus,
  });
  const retryMutation = useRetryOperation();
  const discardMutation = useDiscardOperation();
  const bulkRetryMutation = useBulkRetryOperations();
  const syncStatusQuery = useSyncStatus();
  const mutationPending = retryMutation.isPending || discardMutation.isPending || bulkRetryMutation.isPending;

  const failedTotal = operationsQuery.data?.total;

  React.useEffect(() => {
    if (!operationsQuery.isLoading) {
      setLoadingAnnouncement('');
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setLoadingAnnouncement(__('Loading failed changes…', 'alt-context'));
    }, 0);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [operationsQuery.isLoading]);

  // E15-35 Slice 2 review fix: the armed confirmation is time-boxed and scoped to the
  // backlog it was armed against — it auto-disarms after a short window and whenever the
  // failed total changes, so a stale confirm can never fire against a different backlog.
  React.useEffect(() => {
    if (!bulkRetryArmed) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      dispatch({ type: 'setBulkRetryArmed', armed: false });
    }, BULK_RETRY_ARM_TIMEOUT_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [bulkRetryArmed]);

  React.useEffect(() => {
    dispatch({ type: 'setBulkRetryArmed', armed: false });
  }, [failedTotal]);

  const handleRetry = async (operation: OutboxOperation): Promise<void> => {
    const operationIdentity = formatOperationIdentity(operation);
    dispatch({ type: 'setNotice', notice: null });
    dispatch({ type: 'setMutationError', error: null });
    dispatch({
      type: 'setActionStatus',
      status: sprintf(__('Retrying %s.', 'alt-context'), operationIdentity),
    });
    try {
      await retryMutation.mutateAsync(operation.id);
      dispatch({ type: 'setPendingDiscardId', id: null });
      dispatch({ type: 'setMutationError', error: null });
      dispatch({ type: 'setActionStatus', status: '' });
      dispatch({
        type: 'setNotice',
        notice: sprintf(__('%s queued to retry.', 'alt-context'), operationIdentity),
      });
    } catch {
      dispatch({ type: 'setNotice', notice: null });
      dispatch({ type: 'setActionStatus', status: '' });
      dispatch({
        type: 'setMutationError',
        error: sprintf(__('Unable to retry %s. Please try again.', 'alt-context'), operationIdentity),
      });
    }
  };

  const handleDiscard = async (operation: OutboxOperation): Promise<void> => {
    const operationIdentity = formatOperationIdentity(operation);
    if (pendingDiscardId !== operation.id) {
      dispatch({ type: 'setMutationError', error: null });
      dispatch({ type: 'setNotice', notice: null });
      dispatch({ type: 'setPendingDiscardId', id: operation.id });
      dispatch({
        type: 'setActionStatus',
        status: sprintf(
          __('Discard armed for %s. Activate Confirm discard to continue.', 'alt-context'),
          operationIdentity,
        ),
      });
      return;
    }

    dispatch({
      type: 'setActionStatus',
      status: sprintf(__('Discarding %s.', 'alt-context'), operationIdentity),
    });
    try {
      await discardMutation.mutateAsync(operation.id);
      dispatch({ type: 'setPendingDiscardId', id: null });
      dispatch({ type: 'setMutationError', error: null });
      dispatch({ type: 'setActionStatus', status: '' });
      dispatch({
        type: 'setNotice',
        notice: sprintf(__('%s discarded.', 'alt-context'), operationIdentity),
      });
    } catch {
      dispatch({ type: 'setNotice', notice: null });
      dispatch({ type: 'setActionStatus', status: '' });
      dispatch({
        type: 'setMutationError',
        error: sprintf(__('Unable to discard %s. Please try again.', 'alt-context'), operationIdentity),
      });
    }
  };

  const handleBulkRetry = async (): Promise<void> => {
    if (!bulkRetryArmed) {
      dispatch({ type: 'setMutationError', error: null });
      dispatch({ type: 'setActionStatus', status: '' });
      dispatch({ type: 'setBulkRetryArmed', armed: true });
      return;
    }

    dispatch({ type: 'setBulkRetryArmed', armed: false });
    try {
      const result = await bulkRetryMutation.mutateAsync();
      dispatch({ type: 'setMutationError', error: null });
      dispatch({
        type: 'setNotice',
        notice:
          result.failed_remaining > 0
            ? sprintf(
                __('%1$d failed changes queued to retry. %2$d remain — run again to queue the rest.', 'alt-context'),
                result.requeued,
                result.failed_remaining,
              )
            : sprintf(__('%d failed changes queued to retry.', 'alt-context'), result.requeued),
      });
    } catch {
      dispatch({ type: 'setNotice', notice: null });
      dispatch({
        type: 'setMutationError',
        error: __('Unable to retry all failed changes. Please try again.', 'alt-context'),
      });
    }
  };

  const handleTimelineStatusChange = (status: TimelineStatusFilter): void => {
    dispatch({ type: 'setTimelineStatus', status });
    dispatch({ type: 'setTimelineOffset', offset: 0 });
  };

  const liveStatus = operationsQuery.isLoading
    ? loadingAnnouncement
    : bulkRetryMutation.isPending
      ? __('Retrying all failed changes…', 'alt-context')
      : actionStatus ||
        (retryMutation.isPending || discardMutation.isPending
          ? __('Failed-change action in progress. Please wait.', 'alt-context')
          : bulkRetryArmed && failedTotal !== undefined
            ? sprintf(
                __('Retry all is armed. Activate Confirm retry all failed to queue %d failed changes.', 'alt-context'),
                failedTotal,
              )
            : (notice ?? ''));

  const statusRegion = (
    <div
      className={notice ? NOTICE_VARIANTS.info : 'screen-reader-text'}
      role={DEAD_LETTER_STATUS.role}
      aria-live={DEAD_LETTER_STATUS.live}
      data-testid={DEAD_LETTER_STATUS.testId}
    >
      {notice ? <span aria-hidden="true">ℹ</span> : null}
      {notice ? ' ' : null}
      {liveStatus}
    </div>
  );

  if (operationsQuery.isLoading) {
    return (
      <section aria-label={__('Failed changes panel', 'alt-context')} aria-busy="true">
        {statusRegion}
        <p>{__('Loading failed changes…', 'alt-context')}</p>
      </section>
    );
  }

  if (operationsQuery.isError || !operationsQuery.data) {
    return (
      <section aria-label={__('Failed changes panel', 'alt-context')}>
        {statusRegion}
        <div className="acx-error-state" role={DEAD_LETTER_STATUS.alertRole}>
          <span aria-hidden="true">⚠</span>
          <p>{__('Unable to load failed changes.', 'alt-context')}</p>
        </div>
      </section>
    );
  }

  const { items, total, limit } = operationsQuery.data;
  const canPageBack = offset > 0;
  const canPageForward = offset + items.length < total;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = offset + items.length;
  const topologyStatus = syncStatusQuery.data?.topology_commands;
  const hasTopologyStatus =
    !!topologyStatus &&
    (topologyStatus.pending > 0 ||
      topologyStatus.applied > 0 ||
      topologyStatus.failed > 0 ||
      topologyStatus.conflict > 0);

  return (
    <section aria-label={__('Failed changes panel', 'alt-context')} aria-busy={mutationPending ? 'true' : undefined}>
      {statusRegion}
      <h3>{__('Failed changes', 'alt-context')}</h3>
      <p>{sprintf(__('Showing %1$d-%2$d of %3$d failed changes.', 'alt-context'), rangeStart, rangeEnd, total)}</p>
      <div className="acx-dashboard__actions">
        {/* E15-35 Slice 2: bulk recovery is inherently N-dependent — at zero the control
            stays visible (count included) but disabled, per rg-003's intent. */}
        <button
          type="button"
          className="button button-secondary"
          onClick={() => {
            void handleBulkRetry();
          }}
          disabled={total === 0 || bulkRetryMutation.isPending || retryMutation.isPending || discardMutation.isPending}
          aria-disabled={mutationPending || total === 0 ? true : undefined}
          aria-describedby={mutationPending ? DEAD_LETTER_PENDING_REASON_ID : undefined}
        >
          {bulkRetryMutation.isPending
            ? __('Retrying all failed…', 'alt-context')
            : bulkRetryArmed
              ? sprintf(__('Confirm retry all failed (%d)', 'alt-context'), total)
              : sprintf(__('Retry all failed (%d)', 'alt-context'), total)}
        </button>
      </div>
      {mutationError ? (
        <div className={NOTICE_VARIANTS.warning} role={DEAD_LETTER_STATUS.alertRole}>
          <span aria-hidden="true">⚠</span>
          <p>{mutationError}</p>
        </div>
      ) : null}
      {hasTopologyStatus ? (
        <div className={NOTICE_VARIANTS.info}>
          <span aria-hidden="true">ℹ</span>
          <p>
            {sprintf(
              SYNC_VOCABULARY.pendingWorkSummary,
              topologyStatus.pending,
              topologyStatus.applied,
              topologyStatus.failed,
              topologyStatus.conflict,
            )}
          </p>
        </div>
      ) : null}
      {mutationPending ? (
        <p id={DEAD_LETTER_PENDING_REASON_ID}>{__('Failed-change action in progress. Please wait.', 'alt-context')}</p>
      ) : null}
      <div className="acx-workbench__panel">
        <h4>{__('Pending changes timeline', 'alt-context')}</h4>
        <div className="acx-dashboard__actions">
          {TIMELINE_STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              className="button button-secondary"
              onClick={() => handleTimelineStatusChange(status)}
              disabled={timelineStatus === status}
            >
              {status === 'all' ? __('All', 'alt-context') : formatStatusLabel(status)}
            </button>
          ))}
        </div>
        {timelineQuery.isLoading ? <p>{__('Loading pending changes…', 'alt-context')}</p> : null}
        {timelineQuery.isError ? <p>{__('Unable to load pending changes.', 'alt-context')}</p> : null}
        {!timelineQuery.isLoading && !timelineQuery.isError && timelineQuery.data ? (
          <>
            <p>
              {sprintf(
                __('Showing %1$d-%2$d of %3$d changes (%4$s).', 'alt-context'),
                timelineQuery.data.total === 0 ? 0 : timelineOffset + 1,
                timelineOffset + timelineQuery.data.items.length,
                timelineQuery.data.total,
                timelineStatus === 'all' ? __('all statuses', 'alt-context') : formatStatusLabel(timelineStatus),
              )}
            </p>
            {timelineQuery.data.items.length === 0 ? (
              <p>{__('No pending changes found for this filter.', 'alt-context')}</p>
            ) : (
              <>
                <ul className="acx-dashboard__activity-list">
                  {timelineQuery.data.items.map((operation) => (
                    <li key={`timeline-${operation.id}`} className="acx-dashboard__activity-item">
                      <div>
                        <strong>{formatOperationType(operation.operation_type)}</strong>
                        <p>{sprintf(__('Status: %s', 'alt-context'), formatStatusLabel(operation.status))}</p>
                        <p>
                          {sprintf(
                            __('Entity: %1$s (%2$s)', 'alt-context'),
                            operation.entity_key,
                            operation.entity_type,
                          )}
                        </p>
                        <p>{sprintf(__('Created: %s', 'alt-context'), formatTimestamp(operation.created_at))}</p>
                        {operation.last_attempted_at ? (
                          <p>
                            {sprintf(
                              __('Last attempted: %s', 'alt-context'),
                              formatTimestamp(operation.last_attempted_at),
                            )}
                          </p>
                        ) : null}
                        {operation.acknowledged_at ? (
                          <p>
                            {sprintf(__('Acknowledged: %s', 'alt-context'), formatTimestamp(operation.acknowledged_at))}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="acx-dashboard__actions">
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => dispatch({ type: 'setTimelineOffset', offset: timelineOffset - TIMELINE_PAGE_SIZE })}
                    disabled={timelineOffset === 0}
                  >
                    {__('Previous timeline page', 'alt-context')}
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => dispatch({ type: 'setTimelineOffset', offset: timelineOffset + TIMELINE_PAGE_SIZE })}
                    disabled={timelineOffset + timelineQuery.data.items.length >= timelineQuery.data.total}
                  >
                    {__('Next timeline page', 'alt-context')}
                  </button>
                </div>
              </>
            )}
          </>
        ) : null}
      </div>
      {items.length === 0 ? (
        <p>{__('No failed changes.', 'alt-context')}</p>
      ) : (
        <>
          <ul className="acx-dashboard__activity-list">
            {items.map((operation) => {
              const payloadSummary = formatPayloadSummary(operation.payload);
              const discardPending = pendingDiscardId === operation.id;

              return (
                <li key={operation.id} className="acx-dashboard__activity-item">
                  <div>
                    <strong>{formatOperationType(operation.operation_type)}</strong>
                    <p>
                      {sprintf(__('Entity: %1$s (%2$s)', 'alt-context'), operation.entity_key, operation.entity_type)}
                    </p>
                    <p>{sprintf(__('Attempts: %d', 'alt-context'), operation.attempts)}</p>
                    <p>
                      {sprintf(__('Last attempted: %s', 'alt-context'), formatTimestamp(operation.last_attempted_at))}
                    </p>
                    <p>{sprintf(__('Error: %s', 'alt-context'), formatErrorSummary(operation))}</p>
                    {payloadSummary ? <p>{payloadSummary}</p> : null}
                  </div>
                  <div className="acx-dashboard__actions">
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => {
                        void handleRetry(operation);
                      }}
                      disabled={retryMutation.isPending || discardMutation.isPending}
                      aria-disabled={retryMutation.isPending || discardMutation.isPending ? true : undefined}
                      aria-describedby={
                        retryMutation.isPending || discardMutation.isPending ? DEAD_LETTER_PENDING_REASON_ID : undefined
                      }
                    >
                      {__('Retry', 'alt-context')}
                    </button>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => {
                        void handleDiscard(operation);
                      }}
                      disabled={retryMutation.isPending || discardMutation.isPending}
                      aria-disabled={retryMutation.isPending || discardMutation.isPending ? true : undefined}
                      aria-describedby={
                        retryMutation.isPending || discardMutation.isPending ? DEAD_LETTER_PENDING_REASON_ID : undefined
                      }
                    >
                      {discardPending ? __('Confirm discard', 'alt-context') : __('Discard', 'alt-context')}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="acx-dashboard__actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => dispatch({ type: 'setOffset', offset: offset - limit })}
              disabled={!canPageBack}
            >
              {__('Previous', 'alt-context')}
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => dispatch({ type: 'setOffset', offset: offset + limit })}
              disabled={!canPageForward}
            >
              {__('Next', 'alt-context')}
            </button>
          </div>
        </>
      )}
    </section>
  );
};

export default DeadLetterPanel;
