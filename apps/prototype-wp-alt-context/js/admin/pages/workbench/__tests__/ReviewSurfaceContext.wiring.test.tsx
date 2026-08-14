import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { WorkbenchProvider } from '../WorkbenchContext';
import { useReviewSurface } from '../ReviewSurfaceContext';

/**
 * BR-01: the isolated ReviewSurfaceContext test proves the provider works, and the
 * ScanTabContent suites mock the hook — so neither would catch `<ReviewSurfaceProvider>`
 * being deleted from the WorkbenchProvider composition. This test renders the REAL
 * WorkbenchProvider stack (no mock) around a `useReviewSurface` consumer.
 */
const Probe = (): React.JSX.Element => {
  useReviewSurface();
  return <span>wired</span>;
};

describe('WorkbenchProvider wiring — ReviewSurfaceProvider is in the stack (BR-01)', () => {
  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
        recognitionMergeSuggestions: 'http://localhost/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://localhost/recognition/suggestions/name',
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };
  });

  afterEach(() => {
    delete (window as { AltContextAdmin?: unknown }).AltContextAdmin;
  });

  it('mounts a useReviewSurface consumer without throwing', () => {
    // [TEST-15] discrimination: remove <ReviewSurfaceProvider> from WorkbenchContext.tsx and
    // this render throws 'must be used within a ReviewSurfaceProvider' → red.
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <WorkbenchProvider>
            <Probe />
          </WorkbenchProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText('wired')).toBeInTheDocument();
  });
});
