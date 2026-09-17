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

export const DESCRIBE_OPERATION_CONTEXT_VERSION = 1 as const;

export interface DescribeOperationRequest {
  writeAlt: boolean;
  force: boolean;
}

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
}

export const DESCRIBE_OPERATION_STORAGE_PREFIX = 'acx_describe_op_v1';

export const describeOperationRunStorageKey = (tenantId: string): string =>
  `${DESCRIBE_OPERATION_STORAGE_PREFIX}:${tenantId}:run`;

export const describeOperationMediaStorageKey = (tenantId: string, mediaId: number): string =>
  `${DESCRIBE_OPERATION_STORAGE_PREFIX}:${tenantId}:media:${mediaId}`;

const listeners = new Set<() => void>();

type TenantScope = string | null;

// Keep the fallback memory cache tenant-scoped too. sessionStorage is keyed by
// tenant, but a page can change its config without reloading (and tests do so
// deliberately); a single process-wide context would otherwise leak one
// tenant's active operation into the next tenant until storage rehydration.
const runContextByTenant = new Map<TenantScope, DescribeOperationContext>();
const suggestByTenant = new Map<TenantScope, Map<number, DescribeOperationContext>>();

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

const isDescribeOperationKind = (value: unknown): value is DescribeOperationKind =>
  value === DESCRIBE_OPERATION_KIND.SUGGEST || value === DESCRIBE_OPERATION_KIND.RUN;

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

const parseContext = (value: unknown): DescribeOperationContext | null => {
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
  const idFromOperationId =
    typeof record.operation_id === 'string' && record.operation_id !== '' ? record.operation_id : null;
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
  };
};

const budgetStartMs = (context: DescribeOperationContext): number =>
  context.warming_started_at ?? context.started_at;

export const isDescribeOperationExpired = (
  context: DescribeOperationContext,
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

const readStorageItem = (key: string): string | null => {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
};

const writeStorageItem = (key: string, value: string): void => {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // Private mode / quota: keep the in-memory half of the (state, context) pair.
  }
};

const removeStorageItem = (key: string): void => {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Ignore storage failures; memory remains the live snapshot.
  }
};

const readStoredContext = (key: string): DescribeOperationContext | null => {
  const raw = readStorageItem(key);
  if (raw === null) {
    return null;
  }
  try {
    const parsed = parseContext(JSON.parse(raw) as unknown);
    if (parsed === null) {
      // Invalid data is not a resumable operation. Remove it at the boundary
      // so a reload cannot repeatedly attempt the same bad payload.
      removeStorageItem(key);
    }
    return parsed;
  } catch {
    removeStorageItem(key);
    return null;
  }
};

const serializeContext = (context: DescribeOperationContext): string =>
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
  });

const hydrateRunFromStorage = (): void => {
  const tenantId = resolveTenantId();
  if (runContextByTenant.has(tenantId)) {
    return;
  }
  if (tenantId === null) {
    return;
  }
  const stored = readStoredContext(describeOperationRunStorageKey(tenantId));
  if (stored?.kind !== DESCRIBE_OPERATION_KIND.RUN) {
    if (stored !== null) {
      removeStorageItem(describeOperationRunStorageKey(tenantId));
    }
    return;
  }
  if (isDescribeOperationExpired(stored)) {
    removeStorageItem(describeOperationRunStorageKey(tenantId));
    return;
  }
  runContextByTenant.set(tenantId, stored);
};

const liveRunContext = (): DescribeOperationContext | null => {
  const tenantId = resolveTenantId();
  hydrateRunFromStorage();
  const current = runContextByTenant.get(tenantId);
  if (current === undefined) {
    return null;
  }
  if (isDescribeOperationExpired(current)) {
    runContextByTenant.delete(tenantId);
    if (tenantId !== null) {
      removeStorageItem(describeOperationRunStorageKey(tenantId));
    }
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
      removeStorageItem(describeOperationMediaStorageKey(tenantId, mediaId));
    }
    return null;
  }
  if (tenantId === null) {
    return null;
  }
  const stored = readStoredContext(describeOperationMediaStorageKey(tenantId, mediaId));
  if (stored?.kind !== DESCRIBE_OPERATION_KIND.SUGGEST) {
    if (stored !== null) {
      removeStorageItem(describeOperationMediaStorageKey(tenantId, mediaId));
    }
    return null;
  }
  if (stored.media_id !== mediaId || isDescribeOperationExpired(stored)) {
    removeStorageItem(describeOperationMediaStorageKey(tenantId, mediaId));
    return null;
  }
  const tenantSuggestContexts =
    suggestByTenant.get(tenantId) ?? new Map<number, DescribeOperationContext>();
  tenantSuggestContexts.set(mediaId, stored);
  suggestByTenant.set(tenantId, tenantSuggestContexts);
  return stored;
};

const purgeInvalid = (): void => {
  const tenantId = resolveTenantId();
  const cachedRun = runContextByTenant.get(tenantId);
  if (cachedRun !== undefined && isDescribeOperationExpired(cachedRun)) {
    runContextByTenant.delete(tenantId);
    if (tenantId !== null) {
      removeStorageItem(describeOperationRunStorageKey(tenantId));
    }
  }

  const cachedSuggest = suggestByTenant.get(tenantId);
  if (cachedSuggest !== undefined) {
    for (const [mediaId, context] of cachedSuggest) {
      if (isDescribeOperationExpired(context)) {
        cachedSuggest.delete(mediaId);
        if (tenantId !== null) {
          removeStorageItem(describeOperationMediaStorageKey(tenantId, mediaId));
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
  const storedRun = readStoredContext(runKey);
  if (
    storedRun !== null &&
    (storedRun.kind !== DESCRIBE_OPERATION_KIND.RUN || isDescribeOperationExpired(storedRun))
  ) {
    removeStorageItem(runKey);
  } else if (storedRun === null && readStorageItem(runKey) !== null) {
    // readStoredContext normally removes malformed JSON/version data; this
    // branch also covers storage implementations that changed between reads.
    removeStorageItem(runKey);
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

const emptySnapshot = (): DescribeOperationContext | null => null;

export const putDescribeOperationContext = (context: DescribeOperationContext): void => {
  const parsed = parseContext(context);
  if (parsed === null || isDescribeOperationExpired(parsed)) {
    return;
  }
  const tenantId = resolveTenantId();
  if (parsed.kind === DESCRIBE_OPERATION_KIND.RUN) {
    runContextByTenant.set(tenantId, parsed);
    if (tenantId !== null) {
      writeStorageItem(describeOperationRunStorageKey(tenantId), serializeContext(parsed));
    }
    emitChange();
    return;
  }
  if (parsed.media_id === undefined) {
    return;
  }
  const tenantSuggestContexts =
    suggestByTenant.get(tenantId) ?? new Map<number, DescribeOperationContext>();
  tenantSuggestContexts.set(parsed.media_id, parsed);
  suggestByTenant.set(tenantId, tenantSuggestContexts);
  if (tenantId !== null) {
    writeStorageItem(
      describeOperationMediaStorageKey(tenantId, parsed.media_id),
      serializeContext(parsed),
    );
  }
  emitChange();
};

export const clearDescribeRunContext = (): void => {
  const tenantId = resolveTenantId();
  const hadRun = runContextByTenant.delete(tenantId);
  const hadStoredRun =
    tenantId !== null && readStorageItem(describeOperationRunStorageKey(tenantId)) !== null;
  if (tenantId !== null) {
    removeStorageItem(describeOperationRunStorageKey(tenantId));
  }
  if (hadRun || hadStoredRun) {
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
  const hadStoredSuggest =
    tenantId !== null &&
    readStorageItem(describeOperationMediaStorageKey(tenantId, mediaId)) !== null;
  if (tenantId !== null) {
    removeStorageItem(describeOperationMediaStorageKey(tenantId, mediaId));
  }
  if (hadSuggest || hadStoredSuggest) {
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
  suggestByTenant.clear();
};
