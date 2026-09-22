import { fetchRequiredApi, UnknownBoundaryError } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import {
  RECLAIMER_VOCABULARY,
  type ReclaimerStatus,
  type SyncHealthResponse,
  type SyncStatusResponse,
  type SyncTriggerResponse,
} from './types';
import { createRecognitionTimeoutSignal } from './requestTimeout';

const isNonNegativeInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0;

const isPositiveInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value > 0;

const isUtcTimestamp = (value: unknown): value is string =>
  typeof value === 'string' &&
  /^\d{4}-\d{2}-\d{2}T[^\s]+Z$/.test(value) &&
  !Number.isNaN(Date.parse(value));

const isNullableUtcTimestamp = (value: unknown): value is string | null =>
  value === null || isUtcTimestamp(value);

const isNullableNonNegativeInteger = (value: unknown): value is number | null =>
  value === null || isNonNegativeInteger(value);

const findVocabularyValue = <T extends string>(
  values: readonly T[],
  value: unknown,
): T | undefined => values.find((candidate) => candidate === value);

/**
 * Validate the reclaimer seam before it reaches presentation code. A deploy
 * skew or a future enum must become null/unknown, never an optimistic healthy
 * state and never a render-time exception.
 */
const normalizeReclaimer = (value: unknown): ReclaimerStatus | null => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null;
  }

  const rawState = Reflect.get(value, 'state');
  const state = findVocabularyValue(Object.values(RECLAIMER_VOCABULARY.state), rawState);
  const rawSchedulerMode = Reflect.get(value, 'scheduler_mode');
  const schedulerMode = findVocabularyValue(
    Object.values(RECLAIMER_VOCABULARY.scheduler_mode),
    rawSchedulerMode,
  );
  const rawLastOutcome = Reflect.get(value, 'last_outcome');
  let lastOutcome: ReclaimerStatus['last_outcome'];
  if (rawLastOutcome === null) {
    lastOutcome = null;
  } else {
    const normalizedOutcome = findVocabularyValue(
      Object.values(RECLAIMER_VOCABULARY.last_outcome),
      rawLastOutcome,
    );
    if (!normalizedOutcome) {
      return null;
    }
    lastOutcome = normalizedOutcome;
  }
  const effectivePeriodSeconds = Reflect.get(value, 'effective_period_seconds');
  const lastAttemptAt = Reflect.get(value, 'last_attempt_at');
  const lastSuccessAt = Reflect.get(value, 'last_success_at');
  const lastPurgedCount = Reflect.get(value, 'last_purged_count');
  const backlogRemaining = Reflect.get(value, 'backlog_remaining');
  const backlogOldestAgeSeconds = Reflect.get(value, 'backlog_oldest_age_seconds');
  const batchCapReached = Reflect.get(value, 'batch_cap_reached');

  if (
    !state ||
    !schedulerMode ||
    !isPositiveInteger(effectivePeriodSeconds) ||
    !isNullableUtcTimestamp(lastAttemptAt) ||
    !isNullableUtcTimestamp(lastSuccessAt) ||
    !isNullableNonNegativeInteger(lastPurgedCount) ||
    !isNullableNonNegativeInteger(backlogRemaining) ||
    !isNullableNonNegativeInteger(backlogOldestAgeSeconds) ||
    typeof batchCapReached !== 'boolean' ||
    (state === RECLAIMER_VOCABULARY.state.HEALTHY && lastSuccessAt === null)
  ) {
    return null;
  }

  return {
    state,
    scheduler_mode: schedulerMode,
    effective_period_seconds: effectivePeriodSeconds,
    last_attempt_at: lastAttemptAt,
    last_success_at: lastSuccessAt,
    last_outcome: lastOutcome,
    last_purged_count: lastPurgedCount,
    backlog_remaining: backlogRemaining,
    backlog_oldest_age_seconds: backlogOldestAgeSeconds,
    batch_cap_reached: batchCapReached,
  };
};

export const fetchSyncHealth = async (): Promise<SyncHealthResponse> => {
  const endpoint = getEndpoint('recognitionSyncHealth');
  return fetchRequiredApi<SyncHealthResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(10_000),
  });
};

export const fetchSyncStatus = async (): Promise<SyncStatusResponse> => {
  const endpoint = getEndpoint('recognitionSyncStatus');
  const response = await fetchRequiredApi<SyncStatusResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(10_000),
  });
  // WHY: fetchRequiredApi only rejects undefined, so null envelopes must be rejected here.
  if (typeof response !== 'object' || response === null || Array.isArray(response)) {
    const message = `Request to ${endpoint} succeeded but returned an invalid response envelope.`;
    throw new UnknownBoundaryError(undefined, message);
  }
  return { ...response, reclaimer: normalizeReclaimer(response.reclaimer) };
};

export const triggerSync = async (): Promise<SyncTriggerResponse> => {
  const endpoint = getEndpoint('recognitionSyncTrigger');
  return fetchRequiredApi<SyncTriggerResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(30_000),
  });
};

export const resetMirror = async (): Promise<SyncTriggerResponse> => {
  const endpoint = getEndpoint('recognitionSyncResetMirror');
  return fetchRequiredApi<SyncTriggerResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(30_000),
  });
};
