import '@testing-library/jest-dom';
import { act, configure } from '@testing-library/react';
import { notifyManager } from '@tanstack/react-query';

notifyManager.setNotifyFunction((fn) => {
  act(fn);
});
notifyManager.setBatchNotifyFunction((fn) => {
  act(fn);
});
notifyManager.setScheduler((fn) => {
  act(fn);
});

configure({
  asyncWrapper: async (callback) => {
    let result: unknown;
    await act(async () => {
      result = await callback();
    });
    return result;
  },
  eventWrapper: (callback) => {
    let result: unknown;
    act(() => {
      result = callback();
    });
    return result;
  },
});

class TestResizeObserver {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  callback: ResizeObserverCallback | ((entries: any[]) => void);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  constructor(callback: ResizeObserverCallback | ((entries: any[]) => void)) {
    this.callback = callback;
  }

  observe(): void {
    // no-op for test environment
  }

  unobserve(): void {
    // no-op for test environment
  }

  disconnect(): void {
    // no-op for test environment
  }
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = TestResizeObserver as typeof ResizeObserver;
}
