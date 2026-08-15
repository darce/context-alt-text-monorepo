import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NAMING_OPTIONS_LIMIT } from '../buildNamingOptions';
import { useClusterSuggestionsLoader } from '../useClusterSuggestionsLoader';
import * as recognitionApi from '../../../../api/recognition';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';

vi.mock('../../../../api/recognition', () => ({
  fetchIdentitiesSuggestions: vi.fn(),
  listRecognitionClusters: vi.fn(),
}));

vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

describe('useClusterSuggestionsLoader', () => {
  const createWrapper = () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { wrapper, queryClient };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
  });

  it('caps at-rest namingOptions at NAMING_OPTIONS_LIMIT when the labelled page is larger', async () => {
    // Predicted first failure (limit: null): namingOptions has length 40.
    const { wrapper, queryClient } = createWrapper();
    vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({
      matches: { 'identity-1': [] },
    });
    const baseCluster = {
      member_ids: [],
      representative_identity: {
        media_id: null,
        bbox: { x: 0, y: 0, width: 0, height: 0 },
      },
      sample_identities: [],
    };
    const labeledPage = Array.from({ length: 40 }, (_, index) => ({
      ...baseCluster,
      id: `cluster-${index}`,
      label: `Labelled ${index}`,
      identity_count: 1,
    }));
    vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
      clusters: labeledPage,
      limit: 50,
      total: 40,
      truncated: false,
    });

    const { result } = renderHook(
      () =>
        useClusterSuggestionsLoader({
          identityId: 'identity-1',
          enabled: true,
          labelInput: '',
          debounceMs: 0,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.atRestShown).toBe(40));
    expect(result.current.isAtRestMode).toBe(true);
    expect(result.current.namingOptions).toHaveLength(NAMING_OPTIONS_LIMIT);
    expect(result.current.namingOptions.length).not.toBe(40);
    expect(result.current.atRestTotal).toBe(40);

    queryClient.clear();
  });
});
