import type { ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { useOverlayParam } from '../useOverlayParam';
import {
  queuePendingQueueState,
  resetPendingSearchWritesForTests,
} from '../pendingSearchWrites';

const wrapperForUrl =
  (url: string) =>
  ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/" element={<>{children}</>} />
      </Routes>
    </MemoryRouter>
  );

describe('useOverlayParam', () => {
  beforeEach(() => {
    resetPendingSearchWritesForTests();
  });

  it('UXW2-1-R3-04: setOverlay merges a queued pending rq into the URL', () => {
    queuePendingQueueState({ kind: 'assignment', band: 'all', index: 0 }, null);

    const { result } = renderHook(
      () => {
        const [, setOverlay] = useOverlayParam('panel', ['conflicts'] as const);
        const [searchParams] = useSearchParams();
        return { setOverlay, search: searchParams.toString() };
      },
      { wrapper: wrapperForUrl('/') },
    );

    act(() => {
      result.current.setOverlay('conflicts');
    });

    expect(result.current.search).toContain('rq=assignment.all.0');
    expect(result.current.search).toContain('panel=conflicts');
  });
});
