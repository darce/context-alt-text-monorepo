import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import * as recognitionApi from '../../../api/recognition';
import { WorkbenchPage } from '../../WorkbenchPage';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

vi.mock('../../../hooks/useJobProgressStream', () => ({
  useJobProgressStream: () => ({
    progress: null,
    status: 'pending',
    isOnline: true,
    etaSeconds: null,
    isPrimary: true,
  }),
}));

// Mock useCombinedScanStatus to prevent polling from triggering async updates
vi.mock('../../../hooks/useRecognitionHooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../hooks/useRecognitionHooks')>();
  return {
    ...actual,
    useCombinedScanStatus: () => ({
      scanStatusQuery: { data: null, isLoading: false, isError: false },
    }),
  };
});

vi.mock('../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../api/recognition')>('../../../api/recognition');
  return {
    ...actual,
    scanFacesBatched: vi.fn(),
    fetchScanStatus: vi.fn(),
    cancelScanJob: vi.fn(),
    clusterFaces: vi.fn(),
    fetchMediaIdentities: vi.fn(),
    fetchPendingSuggestions: vi.fn(),
  };
});

// Mock identity-clusters components to avoid async state updates after test completion.
// This test focuses on the scan → invalidation flow; suggestions have dedicated tests.
vi.mock('../../workbench/identity-clusters', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../workbench/identity-clusters')>();
  return {
    ...actual,
    SuggestionReviewPanel: () => null,
    IdentityClusterList: () => null,
  };
});

describe('WorkbenchPage (integration-lite)', () => {
  const originalFetch = globalThis.fetch;
  let queryClient: QueryClient | null = null;

  class MockEventSource {
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;
    close = vi.fn();
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSED = 2;
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    constructor(_url: string) {
      // no-op
    }
  }

  const renderWithClient = (client: QueryClient) => {
    queryClient = client;
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
    return render(<WorkbenchPage />, { wrapper });
  };

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.EventSource = MockEventSource as unknown as typeof EventSource;
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        workbenchMedia: '/wp-json/acx/v1/media',
        recognitionAnalyze: '/wp-json/acx/v1/recognition/analyze',
        recognitionJobs: '/wp-json/acx/v1/recognition/jobs',
        recognitionCluster: '/wp-json/acx/v1/recognition/cluster',
        recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
        recognitionMediaIdentities: '/wp-json/acx/v1/recognition/media-identities',
        recognitionSuggestions: '/wp-json/acx/v1/recognition/suggestions',
      },
      tenant_id: 'test-tenant',
    };
    resetConfigCache();
  });

  afterEach(async () => {
    // Cancel all pending queries and unmount
    if (queryClient) {
      await queryClient.cancelQueries();
      queryClient.clear();
      queryClient = null;
    }
    cleanup();
    if (originalFetch) {
      globalThis.fetch = originalFetch;
    } else {
      // @ts-expect-error allow cleanup when fetch was undefined
      delete globalThis.fetch;
    }
  });

  it('uses real hooks to trigger scan and invalidate identities', async () => {
    const mediaResponse = {
      items: [
        {
          id: 11,
          title: 'Photo Name',
          altText: null,
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-01T00:00:00Z',
          dimensions: { width: 800, height: 600 },
          tags: [],
        },
      ],
      total: 1,
      totalPages: 1,
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mediaResponse),
    }) as typeof fetch;

    vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue({
      identities_by_media: { '11': [] },
    });

    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.9,
          cluster_label: 'Alex',
          cluster_identity_count: 2,
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });

    vi.mocked(recognitionApi.scanFacesBatched).mockResolvedValue([
      {
        id: 'job-123',
        type: 'analyze',
        status: 'pending',
        progress: { completed: 0, total: 1 },
        started_at: new Date().toISOString(),
        finished_at: null,
      },
    ]);

    vi.mocked(recognitionApi.fetchScanStatus).mockResolvedValue({
      id: 'job-123',
      type: 'analyze',
      status: 'pending',
      progress: { completed: 0, total: 1 },
      started_at: new Date().toISOString(),
      finished_at: null,
    });

    vi.mocked(recognitionApi.cancelScanJob).mockResolvedValue({
      id: 'job-123',
      type: 'analyze',
      status: 'pending',
      progress: { completed: 0, total: 1 },
      started_at: new Date().toISOString(),
      finished_at: null,
    });

    vi.mocked(recognitionApi.clusterFaces).mockResolvedValue({
      id: 'cluster-job',
      type: 'clustering',
      status: 'completed',
      progress: { completed: 0, total: 0 },
      started_at: new Date().toISOString(),
      finished_at: null,
      clusters_created: 0,
      total_identities_clustered: 0,
    });

    const client = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: Infinity,
          refetchOnMount: false,
          refetchOnWindowFocus: false,
          refetchOnReconnect: false,
        },
      },
    });
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    client.setQueryData(
      queryKeys.media.workbenchPage({ page: 1, perPage: 10, search: '', status: 'all' }),
      mediaResponse,
    );
    client.setQueryData(queryKeys.media.identitiesByIds([11]), {
      identities_by_media: { '11': [] },
    });

    renderWithClient(client);

    const rowCheckbox = await screen.findByRole('checkbox', { name: /Select media item Photo Name/i });
    const user = userEvent.setup();
    await user.click(rowCheckbox);

    const scanButton = screen.getByRole('button', { name: /Analyze selected media/i });
    await waitFor(() => expect(scanButton).toBeEnabled());
    await user.click(scanButton);

    await waitFor(() => {
      expect(recognitionApi.scanFacesBatched).toHaveBeenCalledWith({ mediaIds: [11] });
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
    });

    expect(await screen.findByText(/Starting scan/i)).toBeInTheDocument();
  });

  it('renders page 2 media when the queue has multiple pages', async () => {
    const pageOneResponse = {
      items: [
        {
          id: 101,
          title: 'Photo Page One',
          altText: null,
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-01T00:00:00Z',
          dimensions: { width: 1200, height: 800 },
          tags: [],
        },
      ],
      total: 2,
      totalPages: 2,
    };
    const pageTwoResponse = {
      items: [
        {
          id: 102,
          title: 'Photo Page Two',
          altText: 'Alt text available',
          status: 'complete',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-02T00:00:00Z',
          dimensions: { width: 1200, height: 800 },
          tags: [],
        },
      ],
      total: 2,
      totalPages: 2,
    };

    vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue({
      identities_by_media: { '101': [], '102': [] },
    });
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      total: 0,
      limit: 10,
      offset: 0,
    });

    const client = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: Infinity,
          refetchOnMount: false,
          refetchOnWindowFocus: false,
          refetchOnReconnect: false,
        },
      },
    });
    client.setQueryData(
      queryKeys.media.workbenchPage({ page: 1, perPage: 10, search: '', status: 'all' }),
      pageOneResponse,
    );
    client.setQueryData(
      queryKeys.media.workbenchPage({ page: 2, perPage: 10, search: '', status: 'all' }),
      pageTwoResponse,
    );
    client.setQueryData(queryKeys.media.identitiesByIds([101]), { identities_by_media: { '101': [] } });
    client.setQueryData(queryKeys.media.identitiesByIds([102]), { identities_by_media: { '102': [] } });

    renderWithClient(client);

    expect(await screen.findByText('Photo Page One')).toBeInTheDocument();

    const user = userEvent.setup();
    const nextButtons = screen.getAllByRole('button', { name: 'Next' });
    await user.click(nextButtons[0]);

    expect(await screen.findByText('Photo Page Two')).toBeInTheDocument();
    expect(screen.queryByText('Photo Page One')).not.toBeInTheDocument();
  });
});
