import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { OutboxListResponse, OutboxOperation } from '../../api/recognition';
import { useBulkRetryOperations } from '../../hooks/useBulkRetryOperations';
import { useDeadLetterOperations } from '../../hooks/useDeadLetterOperations';
import { useDiscardOperation } from '../../hooks/useDiscardOperation';
import { useOutboxOperations } from '../../hooks/useOutboxOperations';
import { useRetryOperation } from '../../hooks/useRetryOperation';
import { useSyncStatus } from '../../hooks/useSyncStatus';
import { SYNC_VOCABULARY } from './syncVocabulary';
import { EmptyState, EmptyStateVariant } from '../../components/ui/EmptyState';

const PAGE_SIZE = 20;
const TIMELINE_PAGE_SIZE = 10;
/** DIAGNO-M-10 / CARD-09: one page of <= 50, sequential per-ID discard, no batch route. */
const BULK_DISCARD_PAGE_SIZE = 50;
const BULK_RETRY_ARM_TIMEOUT_MS = 8000;
const FAILED_RETENTION_DAYS = 7;
const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const FAILED_RETENTION_MS = FAILED_RETENTION_DAYS * DAY_MS;
const AUTO_ATTEMPT_PAYLOAD_KEY = 'acx_auto_attempts';
const MAX_AUTO_ATTEMPTS = 3;

const NON_RETRYABLE_ERROR_CODES = {
  INVALID_PAYLOAD: 'invalid_payload',
  UNAUTHORIZED: 'unauthorized',
  FORBIDDEN: 'forbidden',
  NOT_FOUND: 'not_found',
} as const;

const TERMINAL_ERROR_CODES = {
  ...NON_RETRYABLE_ERROR_CODES,
  AUTO_RETRY_EXHAUSTED: 'auto_retry_exhausted',
} as const;

const TERMINAL_STATUS = {
  DISCARDED: 'discarded',
} as const;

const TERMINAL_ERROR_CODE_SET = new Set<string>(Object.values(TERMINAL_ERROR_CODES));

const BULK_DISCARD_OUTCOME = {
  DISCARDED: 'discarded',
  FAILED: 'failed',
  STOPPED: 'stopped',
} as const;

type BulkDiscardOutcome = (typeof BULK_DISCARD_OUTCOME)[keyof typeof BULK_DISCARD_OUTCOME];

interface BulkDiscardRowResult {
  id: number;
  identity: string;
  outcome: BulkDiscardOutcome;
}

/** Optional D1 wire fields not yet on the shared OutboxOperation type. */
type FailureAgeOperation = OutboxOperation & {
  first_failed_at?: string | null;
  age_seconds?: number | null;
  oldest_age_seconds?: number | null;
};

type FailureAgeList = OutboxListResponse & {
  now?: string | null;
  oldest_age_seconds?: number | null;
};

interface WpDateSettings {
  timezone?: {
    offset?: number;
  };
}

interface WpDateBootstrap {
  date?: {
    getSettings?: () => WpDateSettings;
  };
}

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
  bulkDiscardArmed: boolean;
  bulkDiscardRunning: boolean;
  bulkDiscardResults: readonly BulkDiscardRowResult[];
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
  | { type: 'setBulkDiscardArmed'; armed: boolean }
  | { type: 'setBulkDiscardRunning'; running: boolean }
  | { type: 'setBulkDiscardResults'; results: readonly BulkDiscardRowResult[] }
  | { type: 'setActionStatus'; status: string }
  | { type: 'setNotice'; notice: string | null }
  | { type: 'setMutationError'; error: string | null };

const INITIAL_STATE: DeadLetterPanelState = {
  offset: 0,
  timelineOffset: 0,
  timelineStatus: 'all',
  pendingDiscardId: null,
  bulkRetryArmed: false,
  bulkDiscardArmed: false,
  bulkDiscardRunning: false,
  bulkDiscardResults: [],
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
      return state.bulkRetryArmed === action.armed
        ? state
        : {
            ...state,
            bulkRetryArmed: action.armed,
            bulkDiscardArmed: action.armed ? false : state.bulkDiscardArmed,
          };
    case 'setBulkDiscardArmed':
      return state.bulkDiscardArmed === action.armed
        ? state
        : {
            ...state,
            bulkDiscardArmed: action.armed,
            bulkRetryArmed: action.armed ? false : state.bulkRetryArmed,
          };
    case 'setBulkDiscardRunning':
      return state.bulkDiscardRunning === action.running ? state : { ...state, bulkDiscardRunning: action.running };
    case 'setBulkDiscardResults':
      return { ...state, bulkDiscardResults: action.results };
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

const MYSQL_WALL_CLOCK = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/;
const HAS_EXPLICIT_TZ = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const AGE_CLOCK_UNAVAILABLE = __(
  'Failed-change age is unavailable because php-outbox-reclaimer did not project first_failed_at, last_attempted_at, created_at, or age_seconds.',
  'alt-context',
);

const getSiteGmtOffsetHours = (): number => {
  const wpDate = (window as Window & { wp?: WpDateBootstrap }).wp?.date;
  const offset = wpDate?.getSettings?.()?.timezone?.offset;
  if (typeof offset === 'number' && Number.isFinite(offset)) {
    return offset;
  }

  const localizedOffset = (window.AltContextAdmin as { gmt_offset?: unknown } | undefined)?.gmt_offset;
  if (typeof localizedOffset === 'number' && Number.isFinite(localizedOffset)) {
    return localizedOffset;
  }

  return 0;
};

const parseWpTimestampMs = (value: string | null | undefined, siteGmtOffsetHours: number): number | null => {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  const wall = MYSQL_WALL_CLOCK.exec(trimmed);
  if (wall) {
    const utcMs = Date.UTC(
      Number(wall[1]),
      Number(wall[2]) - 1,
      Number(wall[3]),
      Number(wall[4]),
      Number(wall[5]),
      Number(wall[6]),
    );
    if (!Number.isFinite(utcMs)) {
      return null;
    }

    return utcMs - siteGmtOffsetHours * HOUR_MS;
  }

  if (!HAS_EXPLICIT_TZ.test(trimmed)) {
    return null;
  }

  const parsed = Date.parse(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatTimestamp = (
  value: string | null | undefined,
  siteGmtOffsetHours: number = getSiteGmtOffsetHours(),
): string => {
  if (!value) {
    return __('Unknown time', 'alt-context');
  }

  const parsedMs = parseWpTimestampMs(value, siteGmtOffsetHours);
  if (parsedMs === null) {
    return value;
  }

  return new Date(parsedMs).toLocaleString();
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

const formatAge = (
  value: string | null | undefined,
  nowMs: number = Date.now(),
  siteGmtOffsetHours: number = getSiteGmtOffsetHours(),
): string => {
  const thenMs = parseWpTimestampMs(value, siteGmtOffsetHours);
  if (thenMs === null) {
    return __('Age: unknown', 'alt-context');
  }

  const ageMs = Math.max(0, nowMs - thenMs);
  if (ageMs < MINUTE_MS) {
    return __('Age: less than a minute', 'alt-context');
  }

  if (ageMs < HOUR_MS) {
    return sprintf(__('Age: %d minutes', 'alt-context'), Math.floor(ageMs / MINUTE_MS));
  }

  if (ageMs < 48 * HOUR_MS) {
    return sprintf(__('Age: %d hours', 'alt-context'), Math.floor(ageMs / HOUR_MS));
  }

  return sprintf(__('Age: %d days', 'alt-context'), Math.floor(ageMs / DAY_MS));
};

const readOptionalNonEmptyString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() !== '' ? value : null;

const readOptionalFiniteNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const readFailureClockStamp = (operation: FailureAgeOperation): string | null =>
  readOptionalNonEmptyString(operation.first_failed_at) ??
  readOptionalNonEmptyString(operation.last_attempted_at) ??
  readOptionalNonEmptyString(operation.created_at);

const readFailureAgeMs = (
  operation: FailureAgeOperation,
  nowMs: number,
  siteGmtOffsetHours: number,
): number | null => {
  const stamp = readFailureClockStamp(operation);
  if (stamp !== null) {
    const thenMs = parseWpTimestampMs(stamp, siteGmtOffsetHours);
    if (thenMs !== null) {
      return Math.max(0, nowMs - thenMs);
    }
  }

  const ageSeconds = readOptionalFiniteNumber(operation.age_seconds);
  if (ageSeconds !== null) {
    return Math.max(0, ageSeconds * 1000);
  }

  const oldestAgeSeconds = readOptionalFiniteNumber(operation.oldest_age_seconds);
  if (oldestAgeSeconds !== null) {
    return Math.max(0, oldestAgeSeconds * 1000);
  }

  return null;
};

const resolveNowMs = (list: FailureAgeList | undefined, siteGmtOffsetHours: number): number => {
  const serverNow = readOptionalNonEmptyString(list?.now);
  if (serverNow !== null) {
    const parsed = parseWpTimestampMs(serverNow, siteGmtOffsetHours);
    if (parsed !== null) {
      return parsed;
    }
  }

  return Date.now();
};

const asFailureAgeList = (list: OutboxListResponse | undefined): FailureAgeList | undefined => list;

const readAutoAttempts = (payload: Record<string, unknown> | undefined): number => {
  if (!payload) {
    return 0;
  }

  const value = payload[AUTO_ATTEMPT_PAYLOAD_KEY];
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
};

const isTerminalOperation = (operation: OutboxOperation): boolean =>
  operation.status === TERMINAL_STATUS.DISCARDED ||
  (operation.last_error_code !== null && TERMINAL_ERROR_CODE_SET.has(operation.last_error_code)) ||
  readAutoAttempts(operation.payload) >= MAX_AUTO_ATTEMPTS;

const isOlderThanRetention = (
  operation: FailureAgeOperation,
  nowMs: number,
  siteGmtOffsetHours: number,
): boolean => {
  const ageMs = readFailureAgeMs(operation, nowMs, siteGmtOffsetHours);
  if (ageMs === null) {
    return false;
  }

  return ageMs >= FAILED_RETENTION_MS;
};

const getErrorHttpStatus = (error: unknown): number | null => {
  if (typeof error !== 'object' || error === null || !('status' in error)) {
    return null;
  }

  const status = error.status;
  return typeof status === 'number' && Number.isFinite(status) ? status : null;
};

const isHaltBulkDiscardError = (error: unknown): boolean => {
  const status = getErrorHttpStatus(error);
  return status !== null && status >= 400 && status < 500;
};

const formatBulkDiscardResult = (result: BulkDiscardRowResult): string => {
  switch (result.outcome) {
    case BULK_DISCARD_OUTCOME.DISCARDED:
      return sprintf(__('%s discarded.', 'alt-context'), result.identity);
    case BULK_DISCARD_OUTCOME.STOPPED:
      return sprintf(
        __('Stopped before discarding %s (authorization or client error).', 'alt-context'),
        result.identity,
      );
    case BULK_DISCARD_OUTCOME.FAILED:
      return sprintf(__('Unable to discard %s.', 'alt-context'), result.identity);
    default: {
      const exhaustive: never = result.outcome;
      return exhaustive;
    }
  }
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
    bulkDiscardArmed,
    bulkDiscardRunning,
    bulkDiscardResults,
    actionStatus,
    notice,
    mutationError,
  } = state;

  const operationsQuery = useDeadLetterOperations({ limit: PAGE_SIZE, offset });
  const bulkDiscardPageQuery = useDeadLetterOperations({
    limit: BULK_DISCARD_PAGE_SIZE,
    offset: 0,
  });
  const timelineQuery = useOutboxOperations({
    limit: TIMELINE_PAGE_SIZE,
    offset: timelineOffset,
    status: timelineStatus === 'all' ? undefined : timelineStatus,
  });
  const retryMutation = useRetryOperation();
  const discardMutation = useDiscardOperation();
  const bulkRetryMutation = useBulkRetryOperations();
  const syncStatusQuery = useSyncStatus();
  const mutationPending =
    retryMutation.isPending ||
    discardMutation.isPending ||
    bulkRetryMutation.isPending ||
    bulkDiscardRunning;

  const failedTotal = operationsQuery.data?.total;
  const siteGmtOffsetHours = getSiteGmtOffsetHours();
  const eligibilityList = asFailureAgeList(bulkDiscardPageQuery.data);
  const nowMs = resolveNowMs(eligibilityList ?? asFailureAgeList(operationsQuery.data), siteGmtOffsetHours);
  const eligibilityReady = Boolean(
    bulkDiscardPageQuery.isSuccess && !bulkDiscardPageQuery.isError && eligibilityList,
  );
  const eligibleOperations =
    eligibilityList && bulkDiscardPageQuery.isSuccess && !bulkDiscardPageQuery.isError
      ? eligibilityList.items
          .filter((operation) => isOlderThanRetention(operation, nowMs, siteGmtOffsetHours))
          .slice(0, BULK_DISCARD_PAGE_SIZE)
      : [];
  const eligibleCount = eligibleOperations.length;
  const canBulkDiscard = eligibilityReady && eligibleCount > 0;
  const missingAgeClock = Boolean(
    eligibilityList &&
      bulkDiscardPageQuery.isSuccess &&
      !bulkDiscardPageQuery.isError &&
      eligibilityList.items.length > 0 &&
      eligibilityList.items.every((operation) => readFailureAgeMs(operation, nowMs, siteGmtOffsetHours) === null),
  );

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
    if (!bulkRetryArmed && !bulkDiscardArmed) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      dispatch({ type: 'setBulkRetryArmed', armed: false });
      dispatch({ type: 'setBulkDiscardArmed', armed: false });
    }, BULK_RETRY_ARM_TIMEOUT_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [bulkRetryArmed, bulkDiscardArmed]);

  React.useEffect(() => {
    dispatch({ type: 'setBulkRetryArmed', armed: false });
    dispatch({ type: 'setBulkDiscardArmed', armed: false });
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

  const handleBulkDiscard = async (): Promise<void> => {
    if (!bulkDiscardArmed) {
      dispatch({ type: 'setMutationError', error: null });
      dispatch({ type: 'setNotice', notice: null });
      dispatch({ type: 'setBulkDiscardResults', results: [] });
      dispatch({ type: 'setActionStatus', status: '' });
      dispatch({ type: 'setBulkDiscardArmed', armed: true });
      return;
    }

    dispatch({ type: 'setBulkDiscardArmed', armed: false });
    dispatch({ type: 'setBulkDiscardRunning', running: true });
    dispatch({ type: 'setBulkDiscardResults', results: [] });
    dispatch({ type: 'setMutationError', error: null });
    dispatch({
      type: 'setActionStatus',
      status: __('Discarding failed changes older than 7 days…', 'alt-context'),
    });

    if (!eligibilityReady) {
      dispatch({ type: 'setBulkDiscardRunning', running: false });
      dispatch({ type: 'setActionStatus', status: '' });
      dispatch({
        type: 'setMutationError',
        error: __('Unable to load eligible failed changes for bulk discard.', 'alt-context'),
      });
      return;
    }

    const candidates = eligibleOperations;
    const failedTotalAtStart = eligibilityList?.total ?? 0;

    if (candidates.length === 0) {
      dispatch({ type: 'setBulkDiscardRunning', running: false });
      dispatch({ type: 'setActionStatus', status: '' });
      dispatch({
        type: 'setNotice',
        notice: __('No failed changes older than 7 days on this page.', 'alt-context'),
      });
      return;
    }

    const results: BulkDiscardRowResult[] = [];
    let halted = false;

    for (const operation of candidates) {
      const identity = formatOperationIdentity(operation);
      dispatch({
        type: 'setActionStatus',
        status: sprintf(__('Discarding %s.', 'alt-context'), identity),
      });

      try {
        await discardMutation.mutateAsync(operation.id);
        results.push({
          id: operation.id,
          identity,
          outcome: BULK_DISCARD_OUTCOME.DISCARDED,
        });
      } catch (error) {
        const halt = isHaltBulkDiscardError(error);
        results.push({
          id: operation.id,
          identity,
          outcome: halt ? BULK_DISCARD_OUTCOME.STOPPED : BULK_DISCARD_OUTCOME.FAILED,
        });
        if (halt) {
          halted = true;
          break;
        }
      }
    }

    const discardedCount = results.filter((result) => result.outcome === BULK_DISCARD_OUTCOME.DISCARDED).length;
    const remainingTotal = Math.max(0, failedTotalAtStart - discardedCount);
    const remainderCopy =
      remainingTotal > 0
        ? sprintf(__('%d remain — run again for the next page.', 'alt-context'), remainingTotal)
        : '';
    dispatch({ type: 'setBulkDiscardResults', results });
    dispatch({ type: 'setBulkDiscardRunning', running: false });
    dispatch({ type: 'setPendingDiscardId', id: null });
    dispatch({ type: 'setActionStatus', status: '' });
    dispatch({
      type: 'setNotice',
      notice: halted
        ? sprintf(
            __('Stopped after an authorization or client error. %d discarded.', 'alt-context'),
            discardedCount,
          ) + (remainderCopy ? ` ${remainderCopy}` : '')
        : discardedCount === results.length
          ? sprintf(__('Discarded %d failed changes older than 7 days.', 'alt-context'), discardedCount) +
            (remainderCopy ? ` ${remainderCopy}` : '')
          : sprintf(
              __('Discarded %1$d of %2$d failed changes older than 7 days.', 'alt-context'),
              discardedCount,
              results.length,
            ) + (remainderCopy ? ` ${remainderCopy}` : ''),
    });
  };

  const handleTimelineStatusChange = (status: TimelineStatusFilter): void => {
    dispatch({ type: 'setTimelineStatus', status });
    dispatch({ type: 'setTimelineOffset', offset: 0 });
  };

  const liveStatus = operationsQuery.isLoading
    ? loadingAnnouncement
    : bulkRetryMutation.isPending
      ? __('Retrying all failed changes…', 'alt-context')
      : bulkDiscardRunning
        ? __('Discarding failed changes older than 7 days…', 'alt-context')
        : actionStatus ||
          (retryMutation.isPending || discardMutation.isPending
            ? __('Failed-change action in progress. Please wait.', 'alt-context')
            : bulkRetryArmed && failedTotal !== undefined
              ? sprintf(
                  __('Retry all is armed. Activate Confirm retry all failed to queue %d failed changes.', 'alt-context'),
                  failedTotal,
                )
              : bulkDiscardArmed
                ? sprintf(
                    __(
                      'Discard %d eligible is armed. Activate Confirm discard %d eligible to continue.',
                      'alt-context',
                    ),
                    eligibleCount,
                    eligibleCount,
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
      <div className="acx-dashboard__actions" data-testid="acx-zone-z-dl-actions">
        {total === 0 ? <p>{__('No failed changes to retry.', 'alt-context')}</p> : null}
        {/* E15-35 Slice 2: bulk recovery is inherently N-dependent — at zero the control
            stays visible (count included) but disabled, per rg-003's intent. */}
        <button
          type="button"
          className="button button-secondary"
          onClick={() => {
            void handleBulkRetry();
          }}
          disabled={total === 0 || mutationPending}
          aria-disabled={mutationPending || total === 0 ? true : undefined}
          aria-describedby={mutationPending ? DEAD_LETTER_PENDING_REASON_ID : undefined}
        >
          {bulkRetryMutation.isPending
            ? __('Retrying all failed…', 'alt-context')
            : bulkRetryArmed
              ? sprintf(__('Confirm retry all failed (%d)', 'alt-context'), total)
              : sprintf(__('Retry all failed (%d)', 'alt-context'), total)}
        </button>
        <button
          type="button"
          className="button button-secondary"
          onClick={() => {
            void handleBulkDiscard();
          }}
          disabled={!canBulkDiscard || mutationPending}
          aria-disabled={!canBulkDiscard || mutationPending ? true : undefined}
          aria-describedby={mutationPending ? DEAD_LETTER_PENDING_REASON_ID : undefined}
        >
          {bulkDiscardRunning
            ? __('Discarding failed older than 7 days…', 'alt-context')
            : bulkDiscardArmed
              ? sprintf(__('Confirm discard %d eligible', 'alt-context'), eligibleCount)
              : sprintf(__('Discard %d eligible', 'alt-context'), eligibleCount)}
        </button>
      </div>
      {missingAgeClock ? (
        <div className={NOTICE_VARIANTS.warning} role={DEAD_LETTER_STATUS.alertRole}>
          <span aria-hidden="true">⚠</span>
          <p>{AGE_CLOCK_UNAVAILABLE}</p>
        </div>
      ) : null}
      {mutationError ? (
        <div className={NOTICE_VARIANTS.warning} role={DEAD_LETTER_STATUS.alertRole}>
          <span aria-hidden="true">⚠</span>
          <p>{mutationError}</p>
        </div>
      ) : null}
      {bulkDiscardResults.length > 0 ? (
        <ul className="acx-dashboard__activity-list" data-testid="acx-bulk-discard-results">
          {bulkDiscardResults.map((result) => (
            <li key={`bulk-discard-${result.id}`}>{formatBulkDiscardResult(result)}</li>
          ))}
        </ul>
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
                        <p>{formatAge(operation.created_at, nowMs)}</p>
                        {isTerminalOperation(operation) ? <p>{__('Will not retry', 'alt-context')}</p> : null}
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
        <EmptyState
          variant={EmptyStateVariant.EMPTY}
          heading={__('No failed changes.', 'alt-context')}
          body={__('Refresh to check whether any changes need recovery.', 'alt-context')}
          action={{
            label: __('Refresh failed changes', 'alt-context'),
            onClick: () => void operationsQuery.refetch(),
          }}
          headingLevel={4}
        />
      ) : (
        <>
          <ul className="acx-dashboard__activity-list">
            {items.map((operation) => {
              const payloadSummary = formatPayloadSummary(operation.payload);
              const discardPending = pendingDiscardId === operation.id;
              const terminal = isTerminalOperation(operation);

              return (
                <li key={operation.id} className="acx-dashboard__activity-item">
                  <div>
                    <strong>{formatOperationType(operation.operation_type)}</strong>
                    <p>
                      {sprintf(__('Entity: %1$s (%2$s)', 'alt-context'), operation.entity_key, operation.entity_type)}
                    </p>
                    <p>{sprintf(__('Attempts: %d', 'alt-context'), operation.attempts)}</p>
                    <p>{formatAge(operation.created_at, nowMs)}</p>
                    {terminal ? <p>{__('Will not retry', 'alt-context')}</p> : null}
                    <p>
                      {sprintf(__('Last attempted: %s', 'alt-context'), formatTimestamp(operation.last_attempted_at))}
                    </p>
                    <p>{sprintf(__('Error: %s', 'alt-context'), formatErrorSummary(operation))}</p>
                    {payloadSummary ? <p>{payloadSummary}</p> : null}
                  </div>
                  <div className="acx-dashboard__actions">
                    {terminal ? null : (
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => {
                          void handleRetry(operation);
                        }}
                        disabled={mutationPending}
                        aria-disabled={mutationPending ? true : undefined}
                        aria-describedby={mutationPending ? DEAD_LETTER_PENDING_REASON_ID : undefined}
                      >
                        {__('Retry', 'alt-context')}
                      </button>
                    )}
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => {
                        void handleDiscard(operation);
                      }}
                      disabled={mutationPending}
                      aria-disabled={mutationPending ? true : undefined}
                      aria-describedby={mutationPending ? DEAD_LETTER_PENDING_REASON_ID : undefined}
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
