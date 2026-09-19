import { useSyncExternalStore } from 'react';

import { getConfig } from '../api/config';

/**
 * Canonical operation-context kind (sr-007). `id` is operation_id for Suggest
 * and run_id for a bulk run (GRPH-29: persist the command, not derived UI).
 */
export const DESCRIBE_OPERATION_KIND = {
  SUGGEST: 'suggest',
  RUN: 'run',
} as const;

export type DescribeOperationKind =
  (typeof DESCRIBE_OPERATION_KIND)[keyof typeof DESCRIBE_OPERATION_KIND];

/** Resume lifecycle for a persisted bulk run (sr-007). Omitted while the run is active. */
export const DESCRIBE_RUN_RESUME_STATUS = {
  ACTIVE: 'active',
  NEEDS_TERMINAL_CHECK: 'needs_terminal_check',
} as const;

export type DescribeRunResumeStatus =
  (typeof DESCRIBE_RUN_RESUME_STATUS)[keyof typeof DESCRIBE_RUN_RESUME_STATUS];

/** Outcome the consumer reports after one GET describe/run/{id} poll (sr-007). */
export const DESCRIBE_RUN_SETTLE_OUTCOME = {
  COMPLETED: 'completed',
  COMPLETED_WITH_ERRORS: 'completed_with_errors',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
  MISSING: 'missing',
  UNRESOLVED: 'unresolved',
} as const;

export type DescribeRunSettleOutcome =
  (typeof DESCRIBE_RUN_SETTLE_OUTCOME)[keyof typeof DESCRIBE_RUN_SETTLE_OUTCOME];

export interface SettledDescribeRun {
  id: string;
  outcome: DescribeRunSettleOutcome;
}

export const DESCRIBE_OPERATION_CONTEXT_VERSION = 1 as const;

export interface DescribeOperationRequest {
  writeAlt: boolean;
  force: boolean;
}

export type DescribeOperationPersistence = 'durable' | 'memory_only';

export interface DescribeOperationContext {
  version: typeof DESCRIBE_OPERATION_CONTEXT_VERSION;
  kind: DescribeOperationKind;
  id: string;
  media_id?: number;
  startup_id: string | null;
  started_at: number;
  warming_started_at?: number;
  startup_budget_seconds?: number;
  request: DescribeOperationRequest;
  /** Whether this snapshot was written to sessionStorage or only kept in memory. */
  persistence: DescribeOperationPersistence;
  status?: DescribeRunResumeStatus;
  progress_mounted?: boolean;
}

/** Input accepted by the store before it attaches the persistence outcome. */
export type DescribeOperationContextInput = Omit<DescribeOperationContext, 'persistence'> & {
  persistence?: DescribeOperationPersistence;
};

type DescribeOperationContextData = Omit<DescribeOperationContext, 'persistence'>;

export const DESCRIBE_OPERATION_STORAGE_PREFIX = 'acx_describe_op_v1';

export const describeOperationRunStorageKey = (tenantId: string): string =>
  `${DESCRIBE_OPERATION_STORAGE_PREFIX}:${tenantId}:run`;

const describeOperationPendingRunStorageKey = (tenantId: string): string =>
  `${DESCRIBE_OPERATION_STORAGE_PREFIX}:${tenantId}:run:pending`;

export const describeOperationMediaStorageKey = (tenantId: string, mediaId: number): string =>
  `${DESCRIBE_OPERATION_STORAGE_PREFIX}:${tenantId}:media:${mediaId}`;

const listeners = new Set<() => void>();

type TenantScope = string | null;

// Keep the fallback memory cache tenant-scoped too. sessionStorage is keyed by
// tenant, but a page can change its config without reloading (and tests do so
// deliberately); a single process-wide context would otherwise leak one
// tenant's active operation into the next tenant until storage rehydration.
const runContextByTenant = new Map<TenantScope, DescribeOperationContext | null>();
const pendingTerminalByTenant = new Map<TenantScope, DescribeOperationContext[]>();
const suggestByTenant = new Map<TenantScope, Map<number, DescribeOperationContext>>();
const lastSettledByTenant = new Map<TenantScope, SettledDescribeRun | null>();

// A failed remove can leave the old storage value in place. Keep a process-local
// tombstone for that key so a later hydration cannot resurrect the cleared run.
// A successful write or remove clears the tombstone.
const storageTombstones = new Set<string>();

const emitChange = (): void => {
  listeners.forEach((listener) => listener());
};

const resolveTenantId = (): string | null => {
  try {
    const tenantId = getConfig().tenant_id;
    return typeof tenantId === 'string' && tenantId !== '' ? tenantId : null;
  } catch {
    return null;
  }
};

export const resolveDescribeOperationTenantId = resolveTenantId;

const isDescribeOperationKind = (value: unknown): value is DescribeOperationKind =>
  value === DESCRIBE_OPERATION_KIND.SUGGEST || value === DESCRIBE_OPERATION_KIND.RUN;

const isDescribeRunResumeStatus = (value: unknown): value is DescribeRunResumeStatus =>
  value === DESCRIBE_RUN_RESUME_STATUS.ACTIVE ||
  value === DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK;

const isDescribeRunSettleOutcome = (value: unknown): value is DescribeRunSettleOutcome =>
  value === DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED ||
  value === DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED_WITH_ERRORS ||
  value === DESCRIBE_RUN_SETTLE_OUTCOME.FAILED ||
  value === DESCRIBE_RUN_SETTLE_OUTCOME.CANCELLED ||
  value === DESCRIBE_RUN_SETTLE_OUTCOME.MISSING ||
  value === DESCRIBE_RUN_SETTLE_OUTCOME.UNRESOLVED;

const parseRequest = (value: unknown): DescribeOperationRequest | null => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (typeof record.writeAlt !== 'boolean' || typeof record.force !== 'boolean') {
    return null;
  }
  return { writeAlt: record.writeAlt, force: record.force };
};

const parsePositiveInt = (value: unknown): number | undefined => {
  if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0) {
    return undefined;
  }
  return value;
};

const parseContext = (value: unknown): DescribeOperationContextData | null => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (record.version !== DESCRIBE_OPERATION_CONTEXT_VERSION) {
    return null;
  }
  if (!isDescribeOperationKind(record.kind)) {
    return null;
  }
  const idFromId = typeof record.id === 'string' && record.id !== '' ? record.id : null;
  // `operation_id` is the service lease identifier used by Suggest. A bulk
  // run must resume by its `run_id`; accepting the alias for a run could make
  // a malformed persisted payload poll the wrong operation after reload.
  const idFromOperationId =
    record.kind === DESCRIBE_OPERATION_KIND.SUGGEST &&
    typeof record.operation_id === 'string' &&
    record.operation_id !== ''
      ? record.operation_id
      : null;
  const id = idFromId ?? idFromOperationId;
  if (id === null) {
    return null;
  }
  if (
    typeof record.started_at !== 'number' ||
    !Number.isFinite(record.started_at) ||
    record.started_at < 0
  ) {
    return null;
  }
  const request = parseRequest(record.request);
  if (request === null) {
    return null;
  }
  if (
    record.startup_id !== undefined &&
    record.startup_id !== null &&
    typeof record.startup_id !== 'string'
  ) {
    return null;
  }
  const startupId = typeof record.startup_id === 'string' ? record.startup_id : null;
  const mediaId = parsePositiveInt(record.media_id);
  if (record.kind === DESCRIBE_OPERATION_KIND.SUGGEST && mediaId === undefined) {
    return null;
  }
  let warmingStartedAt: number | undefined;
  if (record.warming_started_at !== undefined) {
    if (
      typeof record.warming_started_at !== 'number' ||
      !Number.isFinite(record.warming_started_at) ||
      record.warming_started_at < 0
    ) {
      return null;
    }
    warmingStartedAt = record.warming_started_at;
  }
  let startupBudgetSeconds: number | undefined;
  if (record.startup_budget_seconds !== undefined) {
    if (
      typeof record.startup_budget_seconds !== 'number' ||
      !Number.isFinite(record.startup_budget_seconds) ||
      !(record.startup_budget_seconds > 0)
    ) {
      return null;
    }
    startupBudgetSeconds = record.startup_budget_seconds;
  }
  let status: DescribeRunResumeStatus | undefined;
  if (record.status !== undefined) {
    if (!isDescribeRunResumeStatus(record.status)) {
      return null;
    }
    if (record.status !== DESCRIBE_RUN_RESUME_STATUS.ACTIVE) {
      status = record.status;
    }
  }
  let progressMounted: true | undefined;
  if (record.progress_mounted !== undefined) {
    if (typeof record.progress_mounted !== 'boolean') {
      return null;
    }
    if (record.progress_mounted) {
      progressMounted = true;
    }
  }
  return {
    version: DESCRIBE_OPERATION_CONTEXT_VERSION,
    kind: record.kind,
    id,
    ...(mediaId !== undefined ? { media_id: mediaId } : {}),
    startup_id: startupId,
    started_at: record.started_at,
    ...(warmingStartedAt !== undefined ? { warming_started_at: warmingStartedAt } : {}),
    ...(startupBudgetSeconds !== undefined ? { startup_budget_seconds: startupBudgetSeconds } : {}),
    request,
    ...(status !== undefined ? { status } : {}),
    ...(progressMounted !== undefined ? { progress_mounted: progressMounted } : {}),
  };
};

const budgetStartMs = (context: DescribeOperationContextData): number =>
  context.warming_started_at ?? context.started_at;

export const isDescribeOperationExpired = (
  context: DescribeOperationContextData,
  nowMs: number = Date.now(),
): boolean => {
  const budgetSeconds = context.startup_budget_seconds;
  if (
    typeof budgetSeconds !== 'number' ||
    !Number.isFinite(budgetSeconds) ||
    !(budgetSeconds > 0)
  ) {
    return false;
  }
  return nowMs >= budgetStartMs(context) + budgetSeconds * 1000;
};

type StorageReadResult =
  | { kind: 'value'; raw: string }
  | { kind: 'absent' }
  | { kind: 'error' };

const readStorageItem = (key: string): StorageReadResult => {
  try {
    const raw = sessionStorage.getItem(key);
    return raw === null ? { kind: 'absent' } : { kind: 'value', raw };
  } catch {
    return { kind: 'error' };
  }
};

const writeStorageItem = (key: string, value: string): boolean => {
  try {
    sessionStorage.setItem(key, value);
    return true;
  } catch {
    // Private mode / quota: keep the in-memory half of the (state, context) pair.
    return false;
  }
};

const removeStorageItem = (key: string): boolean => {
  try {
    sessionStorage.removeItem(key);
    return true;
  } catch {
    // Ignore storage failures; memory remains the live snapshot.
    return false;
  }
};

const removeStorageWithTombstone = (key: string): boolean => {
  const removed = removeStorageItem(key);
  if (removed) {
    storageTombstones.delete(key);
  } else {
    storageTombstones.add(key);
  }
  return removed;
};

type StoredContextReadResult =
  | { kind: 'value'; context: DescribeOperationContext }
  | { kind: 'absent' }
  | { kind: 'invalid' }
  | { kind: 'error' };

const readStoredContext = (key: string): StoredContextReadResult => {
  const storage = readStorageItem(key);
  if (storage.kind === 'error') {
    // A storage read failure is not the same as an absent key. In particular,
    // do not enter either purge path: the old value may still be resumable.
    return { kind: 'error' };
  }
  if (storage.kind === 'absent') {
    return storage;
  }
  try {
    const parsed = parseContext(JSON.parse(storage.raw) as unknown);
    if (parsed === null) {
      // Invalid data is not a resumable operation. Remove it at the boundary
      // so a reload cannot repeatedly attempt the same bad payload.
      removeStorageWithTombstone(key);
      return { kind: 'invalid' };
    }
    return { kind: 'value', context: { ...parsed, persistence: 'durable' } };
  } catch {
    removeStorageWithTombstone(key);
    return { kind: 'invalid' };
  }
};

const serializeContext = (context: DescribeOperationContextData): string =>
  JSON.stringify({
    version: context.version,
    kind: context.kind,
    id: context.id,
    ...(context.media_id !== undefined ? { media_id: context.media_id } : {}),
    startup_id: context.startup_id,
    started_at: context.started_at,
    ...(context.warming_started_at !== undefined
      ? { warming_started_at: context.warming_started_at }
      : {}),
    ...(context.startup_budget_seconds !== undefined
      ? { startup_budget_seconds: context.startup_budget_seconds }
      : {}),
    request: context.request,
    ...(context.status === DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK
      ? { status: context.status }
      : {}),
    ...(context.progress_mounted === true ? { progress_mounted: true } : {}),
  });

const isPendingTerminalRun = (context: DescribeOperationContext): boolean =>
  context.kind === DESCRIBE_OPERATION_KIND.RUN &&
  (context.status === DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK ||
    isDescribeOperationExpired(context));

const pendingListFor = (tenantId: TenantScope): DescribeOperationContext[] =>
  pendingTerminalByTenant.get(tenantId) ?? [];

const persistPendingList = (tenantId: TenantScope, pending: DescribeOperationContext[]): void => {
  if (tenantId === null) {
    return;
  }
  const key = describeOperationPendingRunStorageKey(tenantId);
  if (pending.length === 0) {
    removeStorageWithTombstone(key);
    return;
  }
  const payload = pending.map((context) => JSON.parse(serializeContext(context)) as unknown);
  const durable = writeStorageItem(key, JSON.stringify(payload));
  if (durable) {
    storageTombstones.delete(key);
  } else {
    storageTombstones.add(key);
  }
};

const setPendingList = (tenantId: TenantScope, pending: DescribeOperationContext[]): void => {
  if (pending.length === 0) {
    pendingTerminalByTenant.delete(tenantId);
  } else {
    pendingTerminalByTenant.set(tenantId, pending);
  }
  persistPendingList(tenantId, pending);
};

const upsertPending = (tenantId: TenantScope, context: DescribeOperationContext): void => {
  const next = pendingListFor(tenantId).filter((item) => item.id !== context.id);
  next.push(context);
  setPendingList(tenantId, next);
};

const removePendingById = (tenantId: TenantScope, id: string): boolean => {
  const current = pendingListFor(tenantId);
  const next = current.filter((item) => item.id !== id);
  if (next.length === current.length) {
    return false;
  }
  setPendingList(tenantId, next);
  return true;
};

const parsePendingStoredPayload = (raw: string): DescribeOperationContext[] | null => {
  try {
    const parsed: unknown = JSON.parse(raw);
    const records = Array.isArray(parsed) ? parsed : [parsed];
    const contexts: DescribeOperationContext[] = [];
    for (const record of records) {
      const context = parseContext(record);
      if (context === null || context.kind !== DESCRIBE_OPERATION_KIND.RUN) {
        continue;
      }
      const durable: DescribeOperationContext = { ...context, persistence: 'durable' };
      if (!isPendingTerminalRun(durable)) {
        continue;
      }
      contexts.push(durable);
    }
    return contexts;
  } catch {
    return null;
  }
};

const hydratePendingFromStorage = (): void => {
  const tenantId = resolveTenantId();
  if (pendingTerminalByTenant.has(tenantId)) {
    return;
  }
  if (tenantId === null) {
    return;
  }
  const key = describeOperationPendingRunStorageKey(tenantId);
  if (storageTombstones.has(key)) {
    return;
  }
  const storage = readStorageItem(key);
  if (storage.kind !== 'value') {
    return;
  }
  const contexts = parsePendingStoredPayload(storage.raw);
  if (contexts === null || contexts.length === 0) {
    removeStorageWithTombstone(key);
    return;
  }
  pendingTerminalByTenant.set(tenantId, contexts);
};

const markRunNeedsTerminalCheck = (
  tenantId: TenantScope,
  context: DescribeOperationContext,
): DescribeOperationContext => {
  const marked: DescribeOperationContext = {
    ...context,
    status: DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK,
  };
  if (tenantId !== null) {
    const key = describeOperationRunStorageKey(tenantId);
    const durable = writeStorageItem(key, serializeContext(marked));
    marked.persistence = durable ? 'durable' : 'memory_only';
    if (durable) {
      storageTombstones.delete(key);
    }
  }
  runContextByTenant.set(tenantId, marked);
  return marked;
};

const hydrateRunFromStorage = (): void => {
  const tenantId = resolveTenantId();
  if (runContextByTenant.has(tenantId)) {
    return;
  }
  if (tenantId === null) {
    return;
  }
  const key = describeOperationRunStorageKey(tenantId);
  if (storageTombstones.has(key)) {
    return;
  }
  const stored = readStoredContext(key);
  if (stored.kind !== 'value') {
    return;
  }
  if (stored.context.kind !== DESCRIBE_OPERATION_KIND.RUN) {
    removeStorageWithTombstone(key);
    return;
  }
  if (stored.context.status === DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK) {
    runContextByTenant.set(tenantId, stored.context);
    return;
  }
  if (isDescribeOperationExpired(stored.context)) {
    markRunNeedsTerminalCheck(tenantId, stored.context);
    return;
  }
  runContextByTenant.set(tenantId, stored.context);
};

const parkLivePendingIfReplacing = (tenantId: TenantScope, nextRunId: string): void => {
  hydrateRunFromStorage();
  hydratePendingFromStorage();
  const current = runContextByTenant.get(tenantId);
  if (current === undefined || current === null || current.id === nextRunId) {
    return;
  }
  if (!isPendingTerminalRun(current)) {
    return;
  }
  const marked =
    current.status === DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK
      ? current
      : markRunNeedsTerminalCheck(tenantId, current);
  upsertPending(tenantId, marked);
};

const liveRunContext = (): DescribeOperationContext | null => {
  const tenantId = resolveTenantId();
  hydrateRunFromStorage();
  const current = runContextByTenant.get(tenantId);
  if (current === undefined || current === null) {
    return null;
  }
  if (current.status === DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK) {
    return null;
  }
  if (isDescribeOperationExpired(current)) {
    markRunNeedsTerminalCheck(tenantId, current);
    return null;
  }
  return current;
};

const liveSuggestContext = (mediaId: number): DescribeOperationContext | null => {
  const tenantId = resolveTenantId();
  const suggestByMediaId = suggestByTenant.get(tenantId);
  const cached = suggestByMediaId?.get(mediaId);
  if (cached !== undefined) {
    if (!isDescribeOperationExpired(cached)) {
      return cached;
    }
    suggestByMediaId?.delete(mediaId);
    if (suggestByMediaId?.size === 0) {
      suggestByTenant.delete(tenantId);
    }
    if (tenantId !== null) {
      removeStorageWithTombstone(describeOperationMediaStorageKey(tenantId, mediaId));
    }
    return null;
  }
  if (tenantId === null) {
    return null;
  }
  const key = describeOperationMediaStorageKey(tenantId, mediaId);
  if (storageTombstones.has(key)) {
    return null;
  }
  const stored = readStoredContext(key);
  if (stored.kind !== 'value') {
    return null;
  }
  if (stored.context.kind !== DESCRIBE_OPERATION_KIND.SUGGEST) {
    removeStorageWithTombstone(key);
    return null;
  }
  if (stored.context.media_id !== mediaId || isDescribeOperationExpired(stored.context)) {
    removeStorageWithTombstone(key);
    return null;
  }
  const tenantSuggestContexts =
    suggestByTenant.get(tenantId) ?? new Map<number, DescribeOperationContext>();
  tenantSuggestContexts.set(mediaId, stored.context);
  suggestByTenant.set(tenantId, tenantSuggestContexts);
  return stored.context;
};

const purgeInvalid = (): void => {
  const tenantId = resolveTenantId();
  const cachedRun = runContextByTenant.get(tenantId);
  if (
    cachedRun !== undefined &&
    cachedRun !== null &&
    cachedRun.status !== DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK &&
    isDescribeOperationExpired(cachedRun)
  ) {
    markRunNeedsTerminalCheck(tenantId, cachedRun);
  }

  const cachedSuggest = suggestByTenant.get(tenantId);
  if (cachedSuggest !== undefined) {
    for (const [mediaId, context] of cachedSuggest) {
      if (isDescribeOperationExpired(context)) {
        cachedSuggest.delete(mediaId);
        if (tenantId !== null) {
          removeStorageWithTombstone(describeOperationMediaStorageKey(tenantId, mediaId));
        }
      }
    }
    if (cachedSuggest.size === 0) {
      suggestByTenant.delete(tenantId);
    }
  }

  if (tenantId === null) {
    return;
  }

  const runKey = describeOperationRunStorageKey(tenantId);
  if (storageTombstones.has(runKey)) {
    return;
  }
  const storedRun = readStoredContext(runKey);
  if (storedRun.kind !== 'value') {
    return;
  }
  if (storedRun.context.kind !== DESCRIBE_OPERATION_KIND.RUN) {
    removeStorageWithTombstone(runKey);
    return;
  }
  if (
    storedRun.context.status !== DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK &&
    isDescribeOperationExpired(storedRun.context)
  ) {
    markRunNeedsTerminalCheck(tenantId, storedRun.context);
  }
};

export const subscribeDescribeOperationStore = (listener: () => void): (() => void) => {
  purgeInvalid();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export const getDescribeRunContext = (): DescribeOperationContext | null => liveRunContext();

export const getDescribeSuggestContext = (mediaId: number): DescribeOperationContext | null =>
  liveSuggestContext(mediaId);

export const pendingTerminalRuns = (): DescribeOperationContext[] => {
  const tenantId = resolveTenantId();
  hydrateRunFromStorage();
  hydratePendingFromStorage();
  const pending = [...pendingListFor(tenantId)];
  const current = runContextByTenant.get(tenantId);
  if (current === undefined || current === null || !isPendingTerminalRun(current)) {
    return pending;
  }
  if (pending.some((item) => item.id === current.id)) {
    return pending;
  }
  if (current.status !== DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK) {
    pending.push(markRunNeedsTerminalCheck(tenantId, current));
    return pending;
  }
  pending.push(current);
  return pending;
};

export const getLastSettledRun = (): SettledDescribeRun | null => {
  const tenantId = resolveTenantId();
  return lastSettledByTenant.get(tenantId) ?? null;
};

export const settleRun = (id: string, outcome: DescribeRunSettleOutcome): void => {
  if (!isDescribeRunSettleOutcome(outcome)) {
    return;
  }
  const tenantId = resolveTenantId();
  hydrateRunFromStorage();
  hydratePendingFromStorage();
  const parked = pendingListFor(tenantId).find((item) => item.id === id);
  if (parked !== undefined && isPendingTerminalRun(parked)) {
    lastSettledByTenant.set(tenantId, { id, outcome });
    removePendingById(tenantId, id);
    emitChange();
    return;
  }
  const current = runContextByTenant.get(tenantId);
  if (current === undefined || current === null || current.id !== id) {
    return;
  }
  if (!isPendingTerminalRun(current)) {
    return;
  }
  lastSettledByTenant.set(tenantId, { id, outcome });
  clearDescribeRunContext();
};

const emptySnapshot = (): DescribeOperationContext | null => null;

export const putDescribeOperationContext = (context: DescribeOperationContextInput): void => {
  const parsed = parseContext(context);
  if (parsed === null || isDescribeOperationExpired(parsed)) {
    return;
  }
  const tenantId = resolveTenantId();
  if (parsed.kind === DESCRIBE_OPERATION_KIND.RUN) {
    parkLivePendingIfReplacing(tenantId, parsed.id);
    removePendingById(tenantId, parsed.id);
    let persistence: DescribeOperationPersistence = 'memory_only';
    if (tenantId !== null) {
      const key = describeOperationRunStorageKey(tenantId);
      const durable = writeStorageItem(key, serializeContext(parsed));
      persistence = durable ? 'durable' : 'memory_only';
      if (durable) {
        storageTombstones.delete(key);
      } else {
        storageTombstones.add(key);
      }
    }
    runContextByTenant.set(tenantId, { ...parsed, persistence });
    emitChange();
    return;
  }
  if (parsed.media_id === undefined) {
    return;
  }
  const tenantSuggestContexts =
    suggestByTenant.get(tenantId) ?? new Map<number, DescribeOperationContext>();
  let persistence: DescribeOperationPersistence = 'memory_only';
  if (tenantId !== null) {
    const key = describeOperationMediaStorageKey(tenantId, parsed.media_id);
    const durable = writeStorageItem(key, serializeContext(parsed));
    persistence = durable ? 'durable' : 'memory_only';
    if (durable) {
      storageTombstones.delete(key);
    } else {
      storageTombstones.add(key);
    }
  }
  tenantSuggestContexts.set(parsed.media_id, { ...parsed, persistence });
  suggestByTenant.set(tenantId, tenantSuggestContexts);
  emitChange();
};

export const clearDescribeRunContext = (): void => {
  const tenantId = resolveTenantId();
  const hadRun = runContextByTenant.has(tenantId);
  let hadStoredRun = false;
  let removed = true;
  if (tenantId !== null) {
    const key = describeOperationRunStorageKey(tenantId);
    hadStoredRun = readStorageItem(key).kind === 'value';
    removed = removeStorageWithTombstone(key);
    if (removed) {
      runContextByTenant.delete(tenantId);
    } else {
      // Keep a null snapshot as an in-memory tombstone until the storage layer
      // recovers, so the failed delete cannot be rehydrated in this process.
      runContextByTenant.set(tenantId, null);
    }
  } else {
    runContextByTenant.delete(tenantId);
  }
  if (hadRun || hadStoredRun || !removed) {
    emitChange();
  }
};

export const clearDescribeSuggestContext = (mediaId: number): void => {
  const tenantId = resolveTenantId();
  const tenantSuggestContexts = suggestByTenant.get(tenantId);
  const hadSuggest = tenantSuggestContexts?.delete(mediaId) ?? false;
  if (tenantSuggestContexts?.size === 0) {
    suggestByTenant.delete(tenantId);
  }
  let hadStoredSuggest = false;
  let removed = true;
  if (tenantId !== null) {
    const key = describeOperationMediaStorageKey(tenantId, mediaId);
    hadStoredSuggest = readStorageItem(key).kind === 'value';
    removed = removeStorageWithTombstone(key);
  }
  if (hadSuggest || hadStoredSuggest || !removed) {
    emitChange();
  }
};

export const useDescribeRunContext = (): DescribeOperationContext | null =>
  useSyncExternalStore(subscribeDescribeOperationStore, getDescribeRunContext, emptySnapshot);

export const useDescribeSuggestContext = (mediaId: number): DescribeOperationContext | null =>
  useSyncExternalStore(
    subscribeDescribeOperationStore,
    () => getDescribeSuggestContext(mediaId),
    emptySnapshot,
  );

/** Test-only: drop the in-memory snapshot so the next read rehydrates from sessionStorage. */
export const _resetDescribeOperationStoreForTests = (): void => {
  runContextByTenant.clear();
  pendingTerminalByTenant.clear();
  suggestByTenant.clear();
  lastSettledByTenant.clear();
  // Preserve tombstones while the failed delete's old storage value remains;
  // clear them when the backing key is gone so each test can start cleanly.
  for (const key of storageTombstones) {
    if (readStorageItem(key).kind === 'absent') {
      storageTombstones.delete(key);
    }
  }
};
