import type { ReactNode } from 'react';
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import * as recognitionApi from '../../../api/recognition';
import type { SyncHealthResponse, SyncStatusResponse, SyncTriggerResponse } from '../../../api/recognition';
import { DATA_SOURCE } from '../../../api/recognition/types';
import type { JobStatusResponse } from '../../../api/recognition/types/scan';
import { WorkbenchPage } from '../../WorkbenchPage';

const syncHealthEnvelope = (breakerState: 'open' | 'closed'): SyncHealthResponse => ({
  breaker: {
    state: breakerState,
    base_url: 'http://localhost:8000',
    opened_at: breakerState === 'open' ? '2026-07-14T12:00:00Z' : null,
  },
  outbox: { pending: 0, failed: 0 },
  conflicts: { open: 0 },
  replays: { failed: null, source: 'unavailable_local' },
  last_pull: { at: '2026-07-14T12:00:00Z', ok: true },
  warnings: [],
});

// Mutable ref consumed by the hoisted useCombinedScanStatus mock so individual
// tests can drive the pipeline phase (e.g. awaiting_projection) before render.
const scanStatusRef = vi.hoisted(() => ({ data: null as JobStatusResponse | null }));

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
    lastEventAt: null,
    stalledForSeconds: null,
    retry: vi.fn(),
  }),
}));

// Mock useCombinedScanStatus to prevent polling from triggering async updates
vi.mock('../../../hooks/useRecognitionHooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../hooks/useRecognitionHooks')>();
  return {
    ...actual,
    useCombinedScanStatus: () => ({
      scanStatusQuery: { data: scanStatusRef.data, isLoading: false, isError: false },
      multiScanStatus: [],
      batchRunStatusQuery: { data: undefined, isLoading: false, isError: false },
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
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
    triggerSync: vi.fn(),
    fetchSyncHealth: vi.fn(),
  };
});

// Mock identity-clusters components to avoid async state updates after test completion.
// This test focuses on the scan → invalidation flow; suggestions have dedicated tests.
vi.mock('../../workbench/identity-clusters', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../workbench/identity-clusters')>();
  return {
    ...actual,
    ReviewQueue: () => null,
    IdentityClusterList: () => null,
  };
});

describe('WorkbenchPage (integration-lite)', () => {
  const originalFetch = globalThis.fetch;
  let queryClient: QueryClient | null = null;
  const baseMediaResponse = {
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

  const renderWithClient = (client: QueryClient, initialEntries: string[] = ['/']) => {
    queryClient = client;
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
    return render(<WorkbenchPage />, { wrapper });
  };

  beforeEach(() => {
    vi.clearAllMocks();
    scanStatusRef.data = null;
    vi.mocked(recognitionApi.fetchSyncHealth).mockResolvedValue(syncHealthEnvelope('closed'));
    vi.mocked(recognitionApi.fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(recognitionApi.fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      has_clusters: false,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    window.localStorage.clear();
    window.EventSource = MockEventSource as unknown as typeof EventSource;
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        workbenchMedia: '/wp-json/acx/v1/media',
        recognitionAnalyze: '/wp-json/acx/v1/recognition/analyze',
        recognitionJobs: '/wp-json/acx/v1/recognition/jobs',
        recognitionCluster: '/wp-json/acx/v1/recognition/cluster',
        recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
        recognitionMediaIdentities: '/wp-json/acx/v1/recognition/media-identities',
        recognitionSuggestions: '/wp-json/acx/v1/recognition/suggestions',
        recognitionConflicts: '/wp-json/acx/v1/recognition/conflicts',
        recognitionOutbox: '/wp-json/acx/v1/recognition/outbox',
        recognitionFailedOutbox: '/wp-json/acx/v1/recognition/outbox/failed',
        recognitionSyncStatus: '/wp-json/acx/v1/recognition/sync-status',
        recognitionSyncTrigger: '/wp-json/acx/v1/recognition/sync/trigger',
        recognitionSyncHealth: '/wp-json/acx/v1/recognition/sync/health',
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
    onlineManager.setOnline(true);
    vi.useRealTimers();
    if (originalFetch) {
      globalThis.fetch = originalFetch;
    } else {
      // @ts-expect-error allow cleanup when fetch was undefined
      delete globalThis.fetch;
    }
  });

  it('uses real hooks to trigger scan and invalidate identities', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(baseMediaResponse),
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
      limit: 10,
      offset: 0,
    });

    vi.mocked(recognitionApi.scanFacesBatched).mockResolvedValue({
      batchRunId: 'batch-run-123',
      jobs: [
        {
          id: 'job-123',
          type: 'analyze',
          status: 'pending',
          progress: { completed: 0, total: 1 },
          started_at: new Date().toISOString(),
          finished_at: null,
        },
      ],
    });

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
      baseMediaResponse,
    );
    client.setQueryData(queryKeys.media.identitiesByIds([11]), {
      identities_by_media: { '11': [] },
    });

    renderWithClient(client);

    const user = userEvent.setup();
    const rowCheckbox = await screen.findByRole('checkbox', { name: /Select media item Photo Name/i });
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

    // E21-18 S1: active job surfaces via compact strip chrome (Scanning… / Cancel),
    // not the demoted panel's per-tick statusText live region.
    const strip = await screen.findByTestId('active-job-strip');
    expect(strip).toBeInTheDocument();
    expect(strip.textContent).toMatch(/Scanning/i);
    expect(within(strip).getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it.each([
    {
      name: 'healthy',
      syncStatus: {
        last_snapshot_version: 4,
        last_synced_at: '2026-03-11T10:00:00Z',
        is_stale: false,
        sync_health: 'healthy',
        last_sync_result: 'ok',
        pending_curation_operations: 0,
        failed_curation_operations: 0,
        conflict_count: 0,
        topology_commands: {
          pending: 0,
          applied: 0,
          failed: 0,
          conflict: 0,
          last_reconciled_at: null,
        },
      } satisfies SyncStatusResponse,
      expectedText: 'Fresh',
      linkName: null,
      linkHref: null,
    },
    {
      name: 'queued',
      syncStatus: {
        last_snapshot_version: 4,
        last_synced_at: '2026-03-11T10:00:00Z',
        is_stale: false,
        sync_health: 'queued',
        last_sync_result: 'ok',
        pending_curation_operations: 3,
        failed_curation_operations: 0,
        conflict_count: 0,
        topology_commands: {
          pending: 1,
          applied: 0,
          failed: 0,
          conflict: 0,
          last_reconciled_at: null,
        },
      } satisfies SyncStatusResponse,
      expectedText: 'Waiting to sync',
      linkName: null,
      linkHref: null,
    },
    {
      name: 'stale',
      syncStatus: {
        last_snapshot_version: 4,
        last_synced_at: '2026-03-01T10:00:00Z',
        is_stale: true,
        sync_health: 'stale',
        last_sync_result: 'ok',
        pending_curation_operations: 0,
        failed_curation_operations: 0,
        conflict_count: 0,
        topology_commands: {
          pending: 0,
          applied: 0,
          failed: 0,
          conflict: 0,
          last_reconciled_at: null,
        },
      } satisfies SyncStatusResponse,
      expectedText: 'Stale',
      linkName: null,
      linkHref: null,
    },
    {
      name: 'conflicts',
      syncStatus: {
        last_snapshot_version: 4,
        last_synced_at: '2026-03-11T10:00:00Z',
        is_stale: false,
        sync_health: 'conflicts',
        last_sync_result: 'ok',
        pending_curation_operations: 0,
        failed_curation_operations: 0,
        conflict_count: 2,
        topology_commands: {
          pending: 0,
          applied: 0,
          failed: 0,
          conflict: 0,
          last_reconciled_at: null,
        },
      } satisfies SyncStatusResponse,
      expectedText: 'Conflicts',
      linkName: 'Conflicts',
      linkHref: '#/workbench?tab=scan&panel=conflicts',
    },
    {
      name: 'failures',
      syncStatus: {
        last_snapshot_version: 4,
        last_synced_at: '2026-03-11T10:00:00Z',
        is_stale: false,
        sync_health: 'failures',
        last_sync_result: 'ok',
        pending_curation_operations: 0,
        failed_curation_operations: 2,
        conflict_count: 0,
        topology_commands: {
          pending: 0,
          applied: 0,
          failed: 0,
          conflict: 0,
          last_reconciled_at: null,
        },
      } satisfies SyncStatusResponse,
      expectedText: 'Failures',
      linkName: 'Failures',
      linkHref: '#/workbench?tab=scan&panel=dead-letter',
    },
    {
      name: 'offline',
      syncStatus: {
        last_snapshot_version: 4,
        last_synced_at: '2026-03-11T10:00:00Z',
        is_stale: false,
        sync_health: 'offline',
        last_sync_result: 'unreachable',
        pending_curation_operations: 0,
        failed_curation_operations: 0,
        conflict_count: 0,
        topology_commands: {
          pending: 0,
          applied: 0,
          failed: 0,
          conflict: 0,
          last_reconciled_at: null,
        },
      } satisfies SyncStatusResponse,
      expectedText: 'Offline',
      linkName: null,
      linkHref: null,
    },
  ])(
    'renders sync health state $name with real sync-status data and stable panel links',
    async ({ syncStatus, expectedText, linkName, linkHref }) => {
      vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue({
        identities_by_media: { '11': [] },
      });
      vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
        suggestions: [],
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
        baseMediaResponse,
      );
      client.setQueryData(queryKeys.sync.status(), syncStatus);
      client.setQueryData(queryKeys.media.identitiesByIds([11]), {
        identities_by_media: { '11': [] },
      });

      renderWithClient(client);

      expect(await screen.findByText(expectedText)).toBeInTheDocument();

      if (linkName && linkHref) {
        expect(screen.getByRole('link', { name: linkName })).toHaveAttribute('href', linkHref);
      }
    },
  );

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

  it('hydrates the missing-status media query from the workbench URL', async () => {
    vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue({
      identities_by_media: { '11': [] },
    });
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
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
      queryKeys.media.workbenchPage({ page: 1, perPage: 10, search: '', status: 'missing' }),
      baseMediaResponse,
    );
    client.setQueryData(queryKeys.media.identitiesByIds([11]), { identities_by_media: { '11': [] } });

    renderWithClient(client, ['/workbench?status=missing']);

    expect(await screen.findByText('Photo Name')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveTextContent('Missing alt text');
    expect(
      client.getQueryData(queryKeys.media.workbenchPage({ page: 1, perPage: 10, search: '', status: 'missing' })),
    ).toEqual(baseMediaResponse);
  });

  it('renders its own accessible page heading, matching class-workbench-page.php getPageTitle() (BR-37/BR-38)', async () => {
    // Before this fix, Workbench's accessible name reached into the PHP shell
    // (aria-labelledby="acx-page-title") and was unverifiable from a
    // component-level test: the shell heading only exists on a real
    // server-rendered request. This mounts the REAL, un-mocked WorkbenchPage
    // (not a `vi.mock`-stubbed div, cf. App.test.tsx) and proves the section's
    // accessible name now resolves entirely from its own rendered <h1>.
    vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue({
      identities_by_media: { '11': [] },
    });
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
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
      baseMediaResponse,
    );
    client.setQueryData(queryKeys.media.identitiesByIds([11]), {
      identities_by_media: { '11': [] },
    });

    renderWithClient(client);

    expect(await screen.findByRole('region', { name: 'Review Queue' })).toBeInTheDocument();
  });

  it('paints new findings after projection-ready without reload or remount (E15-23 / E15-24 gate)', async () => {
    vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue({
      identities_by_media: { '11': [] },
    });
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    // Projection sync stays pending until the test resolves it explicitly.
    let resolveSync!: (value: SyncTriggerResponse) => void;
    vi.mocked(recognitionApi.triggerSync).mockImplementation(
      () =>
        new Promise<SyncTriggerResponse>((resolve) => {
          resolveSync = resolve;
        }),
    );

    // Backend reports the pipeline is awaiting projection for snapshot 7.
    scanStatusRef.data = {
      id: 'job-9',
      type: 'clustering',
      status: 'completed',
      progress: { completed: 10, total: 10, phase: 'awaiting_projection' },
      started_at: '2026-06-05T10:00:00Z',
      finished_at: '2026-06-05T10:01:00Z',
      snapshot_version: 7,
      source_job_id: 'job-9',
    } satisfies JobStatusResponse;

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
      baseMediaResponse,
    );
    client.setQueryData(queryKeys.media.identitiesByIds([11]), {
      identities_by_media: { '11': [] },
    });

    renderWithClient(client);

    // Initial paint: queues are empty and the panel says so explicitly.
    expect(
      await screen.findByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).toBeInTheDocument();

    // The projected results become available server-side only now.
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-ready',
          identity_id: 'identity-ready',
          suggested_cluster_id: 'cluster-ready',
          representative_similarity: 0.92,
          avg_member_similarity: 0.9,
          cluster_label: 'Alex',
          cluster_identity_count: 2,
        },
      ],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [
        {
          id: 'top-ready',
          tenant_id: 'test-tenant',
          label: null,
          is_labeled: false,
          is_auto_label: false,
          identity_count: 5,
          user_confirmed: false,
          representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
        },
      ],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    // Projection sync succeeds; no reload, remount, manual cache clear, or
    // delayed passive read happens after this point.
    resolveSync({
      synced: true,
      reason: 'ok',
      last_snapshot_version: 7,
      last_synced_at: '2026-06-05T10:02:00Z',
      is_stale: false,
      sync_health: 'healthy',
      last_sync_result: 'ok',
    });

    expect(await screen.findByText('1 to review')).toBeInTheDocument();
    expect(await screen.findByText('1 unlabeled group')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Review next/ })).toBeEnabled();
    expect(
      screen.queryByText('No findings yet. Run a scan and new findings will appear here automatically.'),
    ).not.toBeInTheDocument();
  });

  it('refetches sync health after reconnect and re-enables the gated analyze CTA', async () => {
    vi.useFakeTimers();

    vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue({
      identities_by_media: { '11': [] },
    });
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(recognitionApi.fetchSyncHealth).mockResolvedValue(syncHealthEnvelope('closed'));

    const client = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: Infinity,
          refetchOnMount: false,
          refetchOnWindowFocus: false,
        },
      },
    });
    client.setQueryData(
      queryKeys.media.workbenchPage({ page: 1, perPage: 10, search: '', status: 'all' }),
      baseMediaResponse,
    );
    client.setQueryData(queryKeys.media.identitiesByIds([11]), {
      identities_by_media: { '11': [] },
    });
    client.setQueryData(queryKeys.sync.health(), syncHealthEnvelope('open'));

    onlineManager.setOnline(false);
    renderWithClient(client);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

    // Banner lives in App.tsx (unit-tested with aria-live); this page-level test
    // proves the gated analyze CTA reacts to the sync-health envelope flip.
    const rowCheckbox = await screen.findByRole('checkbox', { name: /Select media item Photo Name/i });
    await user.click(rowCheckbox);

    const scanButton = await screen.findByRole('button', { name: /Analyze selected media/i });
    // Selection present so the gate is from the breaker, not zero-selection.
    expect(await screen.findByText(/Ready to analyze 1 media item/i)).toBeInTheDocument();
    await waitFor(() => {
      // §7 offline row: aria-disabled + reason, NEVER HTML disabled (still focusable).
      expect(scanButton).not.toBeDisabled();
      expect(scanButton).toHaveAttribute('aria-disabled', 'true');
      expect(scanButton).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
      expect(scanButton).toHaveAttribute('aria-describedby');
    });

    // Reconnect must trigger a real health request without waiting for the next
    // interval. No cache mutation or remount is allowed to heal it.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(recognitionApi.fetchSyncHealth).not.toHaveBeenCalled();

    await act(async () => {
      onlineManager.setOnline(true);
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(recognitionApi.fetchSyncHealth).toHaveBeenCalled();

    expect(scanButton).toBeEnabled();
    expect(scanButton).not.toHaveAttribute('title');
    expect(scanButton).not.toHaveAttribute('aria-disabled');
  });
});
