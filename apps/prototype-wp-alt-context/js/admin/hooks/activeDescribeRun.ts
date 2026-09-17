import { useSyncExternalStore } from 'react';

import {
  clearDescribeRunContext,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  getDescribeRunContext,
  putDescribeOperationContext,
  subscribeDescribeOperationStore,
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

const getProgressMounted = (): boolean => progressMounted;

const getActiveRunId = (): string | null => getDescribeRunContext()?.id ?? null;

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
    return;
  }
  putDescribeOperationContext({
    version: DESCRIBE_OPERATION_CONTEXT_VERSION,
    kind: DESCRIBE_OPERATION_KIND.RUN,
    id: runId,
    startup_id: null,
    started_at: Date.now(),
    request: { writeAlt: false, force: false },
  });
};

export const clearActiveDescribeRunId = (runId: string): void => {
  if (getDescribeRunContext()?.id === runId) {
    clearDescribeRunContext();
  }
};

export const setDescribeProgressMounted = (nextProgressMounted: boolean): void => {
  if (nextProgressMounted === progressMounted) {
    return;
  }
  progressMounted = nextProgressMounted;
  emitProgressChange();
};
