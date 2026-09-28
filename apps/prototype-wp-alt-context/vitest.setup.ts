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
