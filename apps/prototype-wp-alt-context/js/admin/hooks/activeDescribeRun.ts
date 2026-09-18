import { useSyncExternalStore } from 'react';

import {
  clearDescribeRunContext,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  getDescribeRunContext,
  putDescribeOperationContext,
  subscribeDescribeOperationStore,
  type DescribeOperationContextInput,
} from './describeOperationStore';

export interface ActiveDescribeRunState {
  runId: string | null;
  progressMounted: boolean;
}

let progressMounted = false;
const progressListeners = new Set<() => void>();

const emitProgressChange = (): void => {
  progressListeners.forEach((listener) => listener());
};

const subscribeProgressMounted = (listener: () => void): (() => void) => {
  progressListeners.add(listener);
  return () => {
    progressListeners.delete(listener);
  };
};

const getProgressMounted = (): boolean => {
  const existing = getDescribeRunContext();
  if (existing !== null) {
    return existing.progress_mounted === true;
  }
  return progressMounted;
};

const getActiveRunId = (): string | null => getDescribeRunContext()?.id ?? null;

const persistRunContext = (
  existing: DescribeOperationContextInput,
  nextProgressMounted: boolean,
): void => {
  putDescribeOperationContext({
    version: existing.version,
    kind: existing.kind,
    id: existing.id,
    ...(existing.media_id !== undefined ? { media_id: existing.media_id } : {}),
    startup_id: existing.startup_id,
    started_at: existing.started_at,
    ...(existing.warming_started_at !== undefined
      ? { warming_started_at: existing.warming_started_at }
      : {}),
    ...(existing.startup_budget_seconds !== undefined
      ? { startup_budget_seconds: existing.startup_budget_seconds }
      : {}),
    request: existing.request,
    ...(existing.status !== undefined ? { status: existing.status } : {}),
    ...(nextProgressMounted ? { progress_mounted: true } : {}),
  });
};

export const useActiveDescribeRun = (): ActiveDescribeRunState => {
  const runId = useSyncExternalStore(
    subscribeDescribeOperationStore,
    getActiveRunId,
    getActiveRunId,
  );
  const mounted = useSyncExternalStore(
    subscribeProgressMounted,
    getProgressMounted,
    getProgressMounted,
  );
  return { runId, progressMounted: mounted };
};

export const setActiveDescribeRunId = (runId: string | null): void => {
  if (runId === null) {
    clearDescribeRunContext();
    return;
  }
  const existing = getDescribeRunContext();
  if (existing?.id === runId) {
    if ((existing.progress_mounted === true) !== progressMounted) {
      persistRunContext(existing, progressMounted);
    }
    return;
  }
  putDescribeOperationContext({
    version: DESCRIBE_OPERATION_CONTEXT_VERSION,
    kind: DESCRIBE_OPERATION_KIND.RUN,
    id: runId,
    startup_id: null,
    started_at: Date.now(),
    request: { writeAlt: false, force: false },
    ...(progressMounted ? { progress_mounted: true } : {}),
  });
};

export const clearActiveDescribeRunId = (runId: string): void => {
  if (getDescribeRunContext()?.id === runId) {
    clearDescribeRunContext();
  }
};

export const setDescribeProgressMounted = (nextProgressMounted: boolean): void => {
  const existing = getDescribeRunContext();
  const recordMounted = existing?.progress_mounted === true;
  if (nextProgressMounted === progressMounted && recordMounted === nextProgressMounted) {
    return;
  }
  progressMounted = nextProgressMounted;
  if (existing !== null && recordMounted !== nextProgressMounted) {
    persistRunContext(existing, nextProgressMounted);
  }
  emitProgressChange();
};
