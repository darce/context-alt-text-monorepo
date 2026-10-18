/**
 * A local observation bound for a run that is still in its GPU-warming phase.
 * This is deliberately a UI policy fallback, not a backend warm-up SLO.
 */
export const WARMING_OBSERVATION_LIMIT_MS = 600_000;
export const WARMING_OBSERVATION_GRACE_MS = 30_000;

export const WARMING_OBSERVATION_STATUS = {
  NOT_WARMING: 'not_warming',
  WAITING: 'waiting',
  UNKNOWN: 'unknown',
  OVERDUE: 'overdue',
} as const;

export type WarmingObservationStatus =
  (typeof WARMING_OBSERVATION_STATUS)[keyof typeof WARMING_OBSERVATION_STATUS];

export const WARMING_OBSERVATION_EVIDENCE = {
  NOT_WARMING: 'not_warming',
  UNKNOWN: 'unknown',
  STOPPED: 'stopped',
  START_PENDING: 'start_pending',
  STARTING: 'starting',
  WARMING: 'warming',
  READY: 'ready',
  DEGRADED: 'degraded',
  START_FAILED: 'start_failed',
  DEMAND_FAILED: 'demand_failed',
  PROGRESS: 'progress',
} as const;

export type WarmingObservationEvidence =
  (typeof WARMING_OBSERVATION_EVIDENCE)[keyof typeof WARMING_OBSERVATION_EVIDENCE];

export interface WarmingObservationStorage {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
}

export interface WarmingObservationInput {
  runId?: string | null;
  startupId?: string | null;
  run_id?: string | null;
  startup_id?: string | null;
  isWarming?: boolean;
  isTerminal?: boolean;
  now?: number | (() => number);
  atMs?: number;
  clock?: () => number;
  storage?: WarmingObservationStorage | null;
  sessionStorage?: WarmingObservationStorage | null;
  gpuStatus?: unknown;
  gpu_status?: unknown;
  gpu?: unknown;
  run?: unknown;
  gpuState?: unknown;
  snapshotFresh?: unknown;
  snapshot_fresh?: unknown;
  gpuSnapshotFresh?: unknown;
  statusFresh?: unknown;
  intent?: unknown;
  intentStatus?: unknown;
  intent_status?: unknown;
  reason?: unknown;
  isError?: boolean;
  isGpuStatusError?: boolean;
  gpuStatusError?: boolean;
  phaseStartedAt?: number | string | null;
  phaseStartAt?: number | string | null;
  phase_started_at?: number | string | null;
  phaseStartMs?: number | string | null;
  warmingStartedAt?: number | string | null;
  warming_started_at?: number | string | null;
  resumedProgress?: boolean;
  progressResumed?: boolean;
  progressed?: boolean;
  processed?: number | null;
  previousProcessed?: number | null;
  progress?:
    | number
    | { completed?: number; failed?: number; skipped?: number; processed?: number }
    | null;
}

export interface WarmingObservation {
  status: WarmingObservationStatus;
  firstObservedAt: number | null;
  deadlineAt: number | null;
  evidence: WarmingObservationEvidence;
}

export const WARMING_OBSERVATION_STORAGE_KEY_PREFIX = 'acx:warming-observation:v1:';

const GPU_STATES = new Set(['unknown', 'stopped', 'starting', 'warming', 'ready', 'degraded']);
const GPU_INTENT_ACTIONS = new Set(['start', 'stop', 'auto']);
const GPU_INTENT_STATUSES = new Set([
  'none',
  'pending',
  'honoured',
  'blocked_work_in_flight',
  'stopped_with_work',
  'expired',
]);

const memoryFirstObservedAt = new Map<string, number>();
const memoryFallbackKeys = new Set<string>();
const memoryClearedKeys = new Set<string>();

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const hasOwn = (value: Record<string, unknown>, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);

const finiteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const valueFor = (record: Record<string, unknown>, ...keys: string[]): unknown => {
  for (const key of keys) {
    if (hasOwn(record, key)) {
      return record[key];
    }
  }
  return undefined;
};

const asStorage = (value: unknown): WarmingObservationStorage | null => {
  if (!isRecord(value)) {
    return null;
  }
  if (
    typeof value.getItem !== 'function' ||
    typeof value.setItem !== 'function' ||
    typeof value.removeItem !== 'function'
  ) {
    return null;
  }
  return value as unknown as WarmingObservationStorage;
};

const browserSessionStorage = (): WarmingObservationStorage | null => {
  try {
    if (typeof window === 'undefined') {
      return null;
    }
    return asStorage(window.sessionStorage);
  } catch {
    return null;
  }
};

const resolveStorage = (input: WarmingObservationInput): WarmingObservationStorage | null => {
  if (input.storage !== undefined) {
    return asStorage(input.storage);
  }
  if (input.sessionStorage !== undefined) {
    return asStorage(input.sessionStorage);
  }
  return browserSessionStorage();
};

const resolvedNow = (input: WarmingObservationInput): number => {
  const candidate =
    typeof input.now === 'function'
      ? input.now()
      : input.now ?? input.atMs ?? input.clock?.() ?? Date.now();
  return finiteNumber(candidate) ? candidate : Date.now();
};

const asTimestampMs = (value: unknown, now: number): number | null => {
  if (finiteNumber(value)) {
    if (value < 0) {
      return null;
    }
    // `gpu_state.since` is epoch seconds, while the helper's clock is ms.
    if (value > 0 && value < 100_000_000_000 && now >= 100_000_000_000) {
      return value * 1000;
    }
    return value;
  }
  if (typeof value !== 'string' || value === '') {
    return null;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
};

export const warmingObservationStorageKey = (
  runId: string,
  startupId: string | null,
): string =>
  `${WARMING_OBSERVATION_STORAGE_KEY_PREFIX}${encodeURIComponent(runId)}:${encodeURIComponent(
    startupId ?? 'null',
  )}`;

export const getWarmingObservationStorageKey = warmingObservationStorageKey;

const parseStoredFirstObservedAt = (value: string | null): number | null => {
  if (value === null || value === '') {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(value);
    if (finiteNumber(parsed) && parsed >= 0) {
      return parsed;
    }
    if (!isRecord(parsed)) {
      return null;
    }
    const firstObservedAt = valueFor(parsed, 'firstObservedAt', 'first_observed_at');
    return finiteNumber(firstObservedAt) && firstObservedAt >= 0 ? firstObservedAt : null;
  } catch {
    return null;
  }
};

const readStoredFirstObservedAt = (
  storage: WarmingObservationStorage | null,
  key: string,
): { ok: boolean; value: number | null } => {
  if (storage === null) {
    return { ok: false, value: null };
  }
  if (memoryClearedKeys.has(key)) {
    return { ok: true, value: null };
  }
  try {
    return { ok: true, value: parseStoredFirstObservedAt(storage.getItem(key)) };
  } catch {
    return { ok: false, value: null };
  }
};

const persistFirstObservedAt = (
  storage: WarmingObservationStorage | null,
  key: string,
  firstObservedAt: number,
  shouldPersist: boolean,
): void => {
  if (storage === null) {
    memoryFallbackKeys.add(key);
    return;
  }
  if (!shouldPersist) {
    return;
  }
  try {
    storage.setItem(key, JSON.stringify({ firstObservedAt }));
    memoryFallbackKeys.delete(key);
    memoryClearedKeys.delete(key);
  } catch {
    // A browser storage quota/security error must not turn off the watchdog.
    memoryFallbackKeys.add(key);
  }
};

const clearStoredFirstObservedAt = (
  storage: WarmingObservationStorage | null,
  key: string,
): void => {
  memoryFirstObservedAt.delete(key);
  memoryFallbackKeys.delete(key);
  memoryClearedKeys.add(key);
  if (storage === null) {
    return;
  }
  try {
    storage.removeItem(key);
  } catch {
    // The in-memory record is already gone; a later terminal observation can retry.
  }
};

interface NormalizedGpuEvidence {
  evidence: WarmingObservationEvidence;
  explicitFailure: boolean;
  phaseStartedAt: number | null;
}

const unknownGpuEvidence = (phaseStartedAt: number | null = null): NormalizedGpuEvidence => ({
  evidence: WARMING_OBSERVATION_EVIDENCE.UNKNOWN,
  explicitFailure: false,
  phaseStartedAt,
});

const normalizeGpuEvidence = (
  input: WarmingObservationInput,
  now: number,
): NormalizedGpuEvidence => {
  const suppliedStatus = input.gpuStatus ?? input.gpu_status ?? input.gpu;
  const suppliedRecord = isRecord(suppliedStatus) ? suppliedStatus : null;
  const hasQueryWrapper = suppliedRecord !== null && hasOwn(suppliedRecord, 'data');
  const dataRecord =
    hasQueryWrapper && suppliedRecord !== null && isRecord(suppliedRecord.data)
      ? suppliedRecord.data
      : suppliedRecord;
  const record = dataRecord ?? suppliedRecord;

  const statusError =
    input.isError === true ||
    input.isGpuStatusError === true ||
    input.gpuStatusError === true ||
    (suppliedRecord !== null && suppliedRecord.isError === true);
  if (statusError) {
    return unknownGpuEvidence();
  }

  const canonicalGpuState = record?.gpu_state;
  if (record !== null && hasOwn(record, 'gpu_state') && !isRecord(canonicalGpuState)) {
    return unknownGpuEvidence();
  }
  const gpuStateRecord = isRecord(canonicalGpuState) ? canonicalGpuState : null;

  const freshnessValue = hasQueryWrapper
    ? valueFor(suppliedRecord ?? {}, 'snapshotFresh', 'snapshot_fresh') ??
      valueFor(record ?? {}, 'snapshot_fresh', 'snapshotFresh')
    : valueFor(record ?? {}, 'snapshot_fresh', 'snapshotFresh') ??
      valueFor(suppliedRecord ?? {}, 'snapshotFresh', 'snapshot_fresh');
  const resolvedFreshness =
    freshnessValue ??
    input.snapshotFresh ??
    input.snapshot_fresh ??
    input.gpuSnapshotFresh ??
    input.statusFresh;
  if (typeof resolvedFreshness !== 'boolean' || resolvedFreshness === false) {
    return unknownGpuEvidence();
  }

  const rawState =
    valueFor(gpuStateRecord ?? {}, 'state') ??
    valueFor(record ?? {}, 'state', 'gpuState') ??
    valueFor(suppliedRecord ?? {}, 'gpuState', 'state') ??
    input.gpuState;
  if (typeof rawState !== 'string' || !GPU_STATES.has(rawState) || rawState === 'unknown') {
    return unknownGpuEvidence();
  }

  const hasCanonicalFields = gpuStateRecord !== null;
  const rawIntent =
    valueFor(gpuStateRecord ?? {}, 'intent') ?? valueFor(record ?? {}, 'intent') ?? input.intent;
  const topLevelIntent = valueFor(record ?? {}, 'intent');
  const rawIntentStatus =
    valueFor(gpuStateRecord ?? {}, 'intent_status') ??
    valueFor(record ?? {}, 'intentStatus', 'intent_status') ??
    input.intentStatus ??
    input.intent_status;
  const intentStatus = rawIntentStatus ?? (hasCanonicalFields ? undefined : 'none');
  if (typeof intentStatus !== 'string' || !GPU_INTENT_STATUSES.has(intentStatus)) {
    return unknownGpuEvidence();
  }

  let intentAction: string | null = null;
  let intentExpired = intentStatus === 'expired';
  if (rawIntent !== undefined && rawIntent !== null) {
    if (typeof rawIntent !== 'string' || !GPU_INTENT_ACTIONS.has(rawIntent)) {
      return unknownGpuEvidence();
    }
    intentAction = rawIntent;
  }

  if (topLevelIntent !== undefined && topLevelIntent !== null && topLevelIntent !== rawIntent) {
    if (!isRecord(topLevelIntent)) {
      return unknownGpuEvidence();
    }
    const topAction = topLevelIntent.action;
    const expiresAt = topLevelIntent.expires_at;
    if (
      typeof topAction !== 'string' ||
      !GPU_INTENT_ACTIONS.has(topAction) ||
      typeof expiresAt !== 'string'
    ) {
      return unknownGpuEvidence();
    }
    intentAction = topAction;
    const expiresAtMs = asTimestampMs(expiresAt, now);
    if (expiresAtMs === null) {
      return unknownGpuEvidence();
    }
    intentExpired = expiresAtMs <= now;
  }
  if (intentExpired) {
    return unknownGpuEvidence();
  }

  if (intentStatus === 'pending' && intentAction !== 'start') {
    return unknownGpuEvidence();
  }
  if (intentStatus === 'blocked_work_in_flight' && intentAction !== 'stop') {
    return unknownGpuEvidence();
  }
  if (intentStatus === 'stopped_with_work' && intentAction !== 'stop') {
    return unknownGpuEvidence();
  }
  if (intentStatus === 'honoured' && (intentAction === null || intentAction === 'auto')) {
    return unknownGpuEvidence();
  }
  if (intentStatus === 'none' && intentAction !== null && intentAction !== 'auto') {
    return unknownGpuEvidence();
  }

  const reason =
    valueFor(gpuStateRecord ?? {}, 'reason') ??
    valueFor(record ?? {}, 'reason') ??
    input.reason;
  if (reason !== undefined && reason !== null && typeof reason !== 'string') {
    return unknownGpuEvidence();
  }
  const transitionReason = valueFor(gpuStateRecord ?? {}, 'last_transition_reason');
  if (
    transitionReason !== undefined &&
    transitionReason !== null &&
    typeof transitionReason !== 'string'
  ) {
    return unknownGpuEvidence();
  }

  const load = valueFor(record ?? {}, 'load');
  if (load !== undefined && load !== null) {
    if (!isRecord(load) || !hasOwn(load, 'has_work') || typeof load.has_work !== 'boolean') {
      return unknownGpuEvidence();
    }
  }

  const since = valueFor(gpuStateRecord ?? {}, 'since');
  if (since !== undefined && since !== null && asTimestampMs(since, now) === null) {
    return unknownGpuEvidence();
  }
  const phaseStartedAt = asTimestampMs(
      input.phaseStartedAt ??
      input.phaseStartAt ??
      input.phase_started_at ??
      input.phaseStartMs ??
      input.warmingStartedAt ??
      input.warming_started_at ??
      (rawState === 'starting' || rawState === 'warming' ? since : null),
    now,
  );

  if (intentStatus === 'stopped_with_work') {
    return {
      evidence: WARMING_OBSERVATION_EVIDENCE.DEMAND_FAILED,
      explicitFailure: true,
      phaseStartedAt,
    };
  }
  if (reason === 'start_failed' || transitionReason === 'start_failed') {
    return {
      evidence: WARMING_OBSERVATION_EVIDENCE.START_FAILED,
      explicitFailure: true,
      phaseStartedAt,
    };
  }
  if (reason === 'operator_stop_with_work' || transitionReason === 'operator_stop_with_work') {
    return {
      evidence: WARMING_OBSERVATION_EVIDENCE.DEMAND_FAILED,
      explicitFailure: true,
      phaseStartedAt,
    };
  }
  if (rawState === 'degraded') {
    return {
      evidence: WARMING_OBSERVATION_EVIDENCE.DEGRADED,
      explicitFailure: true,
      phaseStartedAt,
    };
  }
  if (rawState === 'stopped') {
    return {
      evidence:
        intentStatus === 'pending'
          ? WARMING_OBSERVATION_EVIDENCE.START_PENDING
          : WARMING_OBSERVATION_EVIDENCE.STOPPED,
      explicitFailure: false,
      phaseStartedAt,
    };
  }
  return {
    evidence:
      rawState === 'starting'
        ? WARMING_OBSERVATION_EVIDENCE.STARTING
        : rawState === 'warming'
          ? WARMING_OBSERVATION_EVIDENCE.WARMING
          : WARMING_OBSERVATION_EVIDENCE.READY,
    explicitFailure: false,
    phaseStartedAt,
  };
};

const hasResumedProgress = (input: WarmingObservationInput): boolean => {
  if (input.resumedProgress === true || input.progressResumed === true || input.progressed === true) {
    return true;
  }
  if (finiteNumber(input.progress)) {
    return input.progress > 0;
  }
  if (isRecord(input.progress)) {
    const processed =
      input.progress.processed ??
      (finiteNumber(input.progress.completed) ? input.progress.completed : 0) +
        (finiteNumber(input.progress.failed) ? input.progress.failed : 0) +
        (finiteNumber(input.progress.skipped) ? input.progress.skipped : 0);
    if (finiteNumber(processed) && processed > 0) {
      return true;
    }
  }
  const processed = input.processed;
  const previousProcessed = input.previousProcessed;
  return finiteNumber(processed) && finiteNumber(previousProcessed) && processed > previousProcessed;
};

const notWarming = (): WarmingObservation => ({
  status: WARMING_OBSERVATION_STATUS.NOT_WARMING,
  firstObservedAt: null,
  deadlineAt: null,
  evidence: WARMING_OBSERVATION_EVIDENCE.NOT_WARMING,
});

/**
 * Derive the bounded warming observation for one `(run_id, startup_id)` key.
 * The first observation is persisted; `now`/`clock` and storage are injectable
 * so this policy remains deterministic in tests and safe when storage is absent.
 */
export const deriveWarmingObservation = (
  input: WarmingObservationInput,
): WarmingObservation => {
  const runRecord = isRecord(input.run) ? input.run : null;
  const runId =
    input.runId ??
    input.run_id ??
    (runRecord !== null && typeof runRecord.run_id === 'string' ? runRecord.run_id : null);
  const startupId =
    input.startupId ??
    input.startup_id ??
    (runRecord !== null &&
      (typeof runRecord.startup_id === 'string' || runRecord.startup_id === null)
      ? runRecord.startup_id
      : null);
  const warming = input.isWarming ?? runRecord?.phase === 'warming';
  const terminal =
    input.isTerminal ??
    (runRecord?.status === 'completed' ||
      runRecord?.status === 'completed_with_errors' ||
      runRecord?.status === 'failed' ||
      runRecord?.status === 'cancelled');

  if (runId === null || !warming) {
    if (terminal && runId !== null) {
      const storage = resolveStorage(input);
      clearStoredFirstObservedAt(storage, warmingObservationStorageKey(runId, startupId));
    }
    return notWarming();
  }

  const now = resolvedNow(input);
  const key = warmingObservationStorageKey(runId, startupId);
  const storage = resolveStorage(input);

  if (terminal) {
    clearStoredFirstObservedAt(storage, key);
    return notWarming();
  }

  const gpuEvidence = normalizeGpuEvidence(input, now);
  const runPhaseStartedAt = asTimestampMs(
    valueFor(runRecord ?? {}, 'phase_started_at', 'phaseStartedAt', 'warming_started_at'),
    now,
  );
  const stored = readStoredFirstObservedAt(storage, key);
  const persistedFirst = stored.value !== null && stored.value <= now ? stored.value : null;
  const fallbackFirst = memoryFirstObservedAt.get(key);
  const useFallback = !stored.ok || memoryFallbackKeys.has(key);
  const candidateFirst = useFallback
    ? Math.min(fallbackFirst ?? now, persistedFirst ?? now)
    : persistedFirst ?? now;
  const phaseStartedAt = gpuEvidence.phaseStartedAt ?? runPhaseStartedAt;
  const firstObservedAt =
    phaseStartedAt !== null && phaseStartedAt <= now
      ? Math.min(candidateFirst, phaseStartedAt)
      : candidateFirst;

  memoryFirstObservedAt.set(key, firstObservedAt);
  persistFirstObservedAt(
    storage,
    key,
    firstObservedAt,
    persistedFirst === null || firstObservedAt < persistedFirst || useFallback,
  );

  const deadlineAt = firstObservedAt + WARMING_OBSERVATION_LIMIT_MS + WARMING_OBSERVATION_GRACE_MS;
  const overdue = now >= deadlineAt;
  const runProgress =
    runRecord === null
      ? undefined
      : {
          completed: finiteNumber(runRecord.completed) ? runRecord.completed : 0,
          failed: finiteNumber(runRecord.failed) ? runRecord.failed : 0,
          skipped: finiteNumber(runRecord.skipped) ? runRecord.skipped : 0,
        };
  const progress = hasResumedProgress({
    ...input,
    progress: input.progress ?? runProgress,
  });

  if (progress) {
    return {
      status: WARMING_OBSERVATION_STATUS.WAITING,
      firstObservedAt,
      deadlineAt,
      evidence: WARMING_OBSERVATION_EVIDENCE.PROGRESS,
    };
  }
  if (gpuEvidence.explicitFailure) {
    return {
      status: WARMING_OBSERVATION_STATUS.OVERDUE,
      firstObservedAt,
      deadlineAt,
      evidence: gpuEvidence.evidence,
    };
  }
  if (overdue) {
    return {
      status: WARMING_OBSERVATION_STATUS.OVERDUE,
      firstObservedAt,
      deadlineAt,
      evidence: gpuEvidence.evidence,
    };
  }
  if (gpuEvidence.evidence === WARMING_OBSERVATION_EVIDENCE.UNKNOWN) {
    return {
      status: WARMING_OBSERVATION_STATUS.UNKNOWN,
      firstObservedAt,
      deadlineAt,
      evidence: gpuEvidence.evidence,
    };
  }
  return {
    status: WARMING_OBSERVATION_STATUS.WAITING,
    firstObservedAt,
    deadlineAt,
    evidence: gpuEvidence.evidence,
  };
};
