import { useSyncExternalStore } from 'react';

export interface ActiveDescribeRunState {
  runId: string | null;
  progressMounted: boolean;
}

let state: ActiveDescribeRunState = {
  runId: null,
  progressMounted: false,
};

const listeners = new Set<() => void>();

const emitChange = (): void => {
  listeners.forEach((listener) => listener());
};

const updateState = (nextState: ActiveDescribeRunState): void => {
  if (nextState.runId === state.runId && nextState.progressMounted === state.progressMounted) {
    return;
  }
  state = nextState;
  emitChange();
};

const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

const getSnapshot = (): ActiveDescribeRunState => state;

export const useActiveDescribeRun = (): ActiveDescribeRunState =>
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

export const setActiveDescribeRunId = (runId: string | null): void => {
  updateState({ ...state, runId });
};

export const clearActiveDescribeRunId = (runId: string): void => {
  if (state.runId === runId) {
    setActiveDescribeRunId(null);
  }
};

export const setDescribeProgressMounted = (progressMounted: boolean): void => {
  updateState({ ...state, progressMounted });
};
