import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { DetectedIdentity } from '../../../api/recognition';
import { MediaSelection } from '../MediaSelection';

interface IdentityQueryState {
  data?: { identities_by_media: Record<string, DetectedIdentity[]>; data_source?: string };
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  isPlaceholderData: boolean;
  isFetching: boolean;
  refetch: () => void;
}

let identitiesQuery: IdentityQueryState;

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[index++]));
  },
}));

vi.mock('../../../api/settingsApi', () => ({
  fetchSettings: vi.fn().mockResolvedValue({ recognition_enabled: false }),
}));

vi.mock('../../../hooks/useBulkDescribe', () => ({
  useBulkDescribe: () => ({
    submit: { isPending: false, mutate: vi.fn(), error: null },
    cancel: { isPending: false, mutate: vi.fn(), error: null },
    progress: {
      status: null,
      run: null,
      isTerminal: false,
      isError: false,
      isPolling: false,
      etaSeconds: null,
      progressFraction: 0,
      retry: vi.fn(),
      error: null,
      stalledForSeconds: null,
      isFrozen: false,
    },
    runId: null,
  }),
}));

vi.mock('../../../hooks/useSyncOffline', () => ({ useSyncOffline: () => false }));

vi.mock('../../../hooks/useRemoteActionGate', () => ({
  useRemoteActionGate: () => ({ title: undefined, 'aria-disabled': undefined }),
}));

vi.mock('../../../hooks/useRecognitionCooldown', () => ({
  useRecognitionCooldown: () => ({ isCoolingDown: false, remainingSeconds: 0, remainingMs: 0 }),
}));

vi.mock('../MediaSelectionTableBody', () => ({
  MediaSelectionTableBody: ({ identitiesLoading }: { identitiesLoading: boolean }) => (
    <tr data-testid="identities-loading" data-loading={String(identitiesLoading)} />
  ),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    selection: {
      selection: {},
      selectedMedia: [],
      toggleRow: vi.fn(),
      toggleAll: vi.fn(),
      isPageFullySelected: () => false,
    },
    filters: {
      searchQuery: '',
      statusFilter: 'all',
      currentPage: 1,
      perPage: 10,
      handleSearchChange: vi.fn(),
      clearSearch: vi.fn(),
      handleStatusChange: vi.fn(),
      setCurrentPage: vi.fn(),
      setPerPage: vi.fn(),
    },
    mediaQueue: {
      mediaQuery: {
        data: { items: [], total: 0, totalPages: 1 },
        isPending: false,
        isFetching: false,
        isError: false,
        isSuccess: true,
        refetch: vi.fn(),
        itemsWithIdentities: [],
        detailQuery: {
          data: { detailsByMedia: {}, limit: 100, total: 0, truncated: false },
          isPending: false,
          isLoading: false,
          isFetching: false,
          isError: false,
          refetch: vi.fn(),
        },
        identitiesQuery,
      },
      statusMessage: '',
      isStatusPending: false,
      detailTruncationNotice: null,
      hasIdentities: false,
    },
  }),
}));

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: false, progress: null },
    scanAndWait: vi.fn(),
    cancelScan: vi.fn(),
    history: { activeJobIds: [] },
  }),
}));

vi.mock('../Panels', () => ({
  isClusteringActive: () => false,
  mediaEditUrl: (id: number) => `#edit-${id}`,
}));

const renderSelection = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MediaSelection />
    </QueryClientProvider>,
  );
};

describe('MediaSelection identities loading derivation', () => {
  beforeEach(() => {
    identitiesQuery = {
      data: { identities_by_media: {}, data_source: 'local_projection' },
      isLoading: false,
      isError: false,
      isPlaceholderData: false,
      isFetching: false,
      refetch: vi.fn(),
    };
  });

  afterEach(cleanup);

  it('shows loading while identities have no initial data', () => {
    identitiesQuery = { ...identitiesQuery, data: undefined, isLoading: true };

    renderSelection();

    expect(screen.getByTestId('identities-loading')).toHaveAttribute('data-loading', 'true');
  });

  it('shows loading while placeholder identities are being replaced', () => {
    identitiesQuery = { ...identitiesQuery, isPlaceholderData: true, isFetching: true };

    renderSelection();

    expect(screen.getByTestId('identities-loading')).toHaveAttribute('data-loading', 'true');
  });

  it('does not show loading for settled identities', () => {
    renderSelection();

    expect(screen.getByTestId('identities-loading')).toHaveAttribute('data-loading', 'false');
  });
});
