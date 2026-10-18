import type { ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import {
  queuePendingQueueState,
  resetPendingSearchWritesForTests,
} from '../../../hooks/pendingSearchWrites';
import { useWorkbenchNav, WorkbenchNavProvider } from '../WorkbenchNavContext';

const wrapperForUrl =
  (url: string) =>
  ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/"
          element={
            <WorkbenchNavProvider>
              {children}
            </WorkbenchNavProvider>
          }
        />
      </Routes>
    </MemoryRouter>
  );

describe('WorkbenchNavContext', () => {
  beforeEach(() => {
    resetPendingSearchWritesForTests();
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {},
    };
  });

  it('UXW2-1-R3-04: setAdvancedOpen merges a queued pending rq into the URL', () => {
    queuePendingQueueState({ kind: 'assignment', band: 'all', index: 0 }, null);

    const { result } = renderHook(
      () => {
        const { setAdvancedOpen } = useWorkbenchNav();
        const [searchParams] = useSearchParams();
        return { setAdvancedOpen, search: searchParams.toString() };
      },
      { wrapper: wrapperForUrl('/') },
    );

    act(() => {
      result.current.setAdvancedOpen(true);
    });

    expect(result.current.search).toContain('rq=assignment.all.0');
    expect(result.current.search).toContain('advanced=open');
  });
});
