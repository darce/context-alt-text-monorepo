import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { IdentityClusterList } from '../identity-clusters';
import * as api from '../../../api/recognition';
import { resetConfigCache } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import type { MediaIdentitiesResponse } from '../../../api/recognition';
import { DATA_SOURCE } from '../../../api/recognition/types';
import { buildNamingOptions } from '../identity-clusters/buildNamingOptions';
import type {
  ClusterSuggestionsLoaderOptions,
  ClusterSuggestionsLoaderResult,
} from '../identity-clusters/useClusterSuggestionsLoader';

const useClusterSuggestionsLoaderMock = vi.hoisted(() => vi.fn<() => ClusterSuggestionsLoaderResult>());

const emptyCollisions = new Map() as ReadonlyMap<string, readonly never[]>;

const loaderResultFrom = (
  partial: Partial<ClusterSuggestionsLoaderResult> & {
    labelMatches?: ClusterSuggestionsLoaderResult['labelMatches'];
  },
): ClusterSuggestionsLoaderResult => {
  const labelMatches = partial.labelMatches ?? [];
  // ClusterSummary.label is runtime-nullable (BR-46); ClusterNamingEntry.label stays string.
  const namedMatches = labelMatches.filter(
    (c): c is typeof c & { label: string } => typeof c.label === 'string' && c.label !== '',
  );
  const built =
    partial.namingOptions !== undefined
      ? null
      : buildNamingOptions({
          rosterEntries: [],
          labelMatches: namedMatches,
          limit: null,
        });
  return {
    identityProjection: partial.identityProjection ?? [],
    namingOptions: partial.namingOptions ?? built?.options ?? [],
    collisionsByLabel: partial.collisionsByLabel ?? built?.collisionsByLabel ?? emptyCollisions,
    labelMatches,
    isLoading: partial.isLoading ?? false,
    rosterError: partial.rosterError ?? false,
    findClusterByLabel: partial.findClusterByLabel ?? defaultFindClusterByLabel,
    atRestTotal: partial.atRestTotal ?? 0,
    atRestTruncated: partial.atRestTruncated ?? false,
    isAtRestMode: partial.isAtRestMode ?? true,
  };
};

interface ClusterLabelMatch {
  id: string;
  label: string;
  identityCount?: number;
}
type FindClusterByLabel = (label: string, signal?: AbortSignal) => Promise<ClusterLabelMatch | null>;
let defaultFindClusterByLabel: ReturnType<typeof vi.fn<FindClusterByLabel>>;
let findClusterDeferreds: Deferred<ClusterLabelMatch | null>[] = [];

// Mock ResizeObserver for Radix UI
window.ResizeObserver = class ResizeObserver {
  observe(): void {
    return undefined;
  }
  unobserve(): void {
    return undefined;
  }
  disconnect(): void {
    return undefined;
  }
};

// Mock PointerCapture for Radix UI
window.HTMLElement.prototype.hasPointerCapture = vi.fn();
window.HTMLElement.prototype.setPointerCapture = vi.fn();
window.HTMLElement.prototype.releasePointerCapture = vi.fn();

// Mock scrollIntoView for cmdk
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// Keep this guard even after deleting useClusterEvents: it catches accidental
// EventSource reintroduction in the identity list render path.
class MockEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close = vi.fn();
  static instances = 0;
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  constructor(_url: string) {
    MockEventSource.instances += 1;
  }
}

const setupMocks = () => {
  // Mock AltContextAdmin config
  (window as unknown as { AltContextAdmin: object }).AltContextAdmin = {
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      recognitionClusters: 'http://localhost:8000/clusters',
      recognitionReassignIdentity: 'http://localhost:8000/reassign-identity',
      recognitionRevertMerge: 'http://localhost:8000/revert-merge',
      recognitionCreateClusterForIdentity: 'http://localhost:8000/create-for-identity',
      recognitionSuggestions: 'http://localhost:8000/suggestions',
    },
    tenant_id: 'test-tenant',
  };

  resetConfigCache();
  MockEventSource.instances = 0;
  window.EventSource = MockEventSource as unknown as typeof EventSource;
};

vi.mock('../identity-clusters/useClusterSuggestionsLoader', () => ({
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  useClusterSuggestionsLoader: (_options: ClusterSuggestionsLoaderOptions) => useClusterSuggestionsLoaderMock(),
}));

vi.mock('../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

vi.mock('../../../api/recognition', () => ({
  mergeCluster: vi.fn(),
  updateClusterLabel: vi.fn(),
  fetchIdentitiesSuggestions: vi.fn(),
  listRecognitionClusters: vi.fn(),
  revertMergeCluster: vi.fn(),
  reassignClusterIdentity: vi.fn(),
  splitCluster: vi.fn(),
  pinRepresentative: vi.fn(),
}));

// Track active query client for cleanup
let activeQueryClient: QueryClient | null = null;

const renderWithClient = async (ui: React.ReactElement) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  activeQueryClient = client;
  const user = userEvent.setup({
    advanceTimers: (ms: number) => vi.advanceTimersByTimeAsync(ms),
  });
  const utils = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  // Flush initial render effects
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  return { client, user, ...utils };
};

const setMediaIdentitiesCache = (client: QueryClient, data: MediaIdentitiesResponse) => {
  client.setQueryData(queryKeys.media.identitiesByIds([1]), data);
};

const baseIdentity = {
  identity_id: 'identity-1',
  representative_id: 'rep-1',
  media_id: 1,
  cluster_id: 'cluster-1',
  cluster_label: 'Cluster 1',
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 10, height: 10 },
  confidence: 0.9,
  similarity: 0.9,
  detected_at: '',
};

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

const SAVE_SUCCESS_DELAY_MS = 1200;
const MATCH_DEBOUNCE_MS = 300;

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const flushTimers = async (advanceMs = 0) => {
  if (advanceMs > 0) {
    await vi.advanceTimersByTimeAsync(advanceMs);
  }
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
};

const resolveDeferred = async <T,>(deferred: Deferred<T>, value: T, advanceMs = 0) => {
  deferred.resolve(value);
  await deferred.promise;
  await flushTimers(advanceMs);
};

const resolveFindClusterDeferreds = async (value: ClusterLabelMatch | null) => {
  while (findClusterDeferreds.length > 0) {
    const deferred = findClusterDeferreds.shift();
    if (deferred) {
      await resolveDeferred(deferred, value);
    }
  }
};

const runWithTimers = async (callback: () => Promise<void> | void, advanceMs = 0) => {
  await callback();
  await flushTimers(advanceMs);
};

const resolveSaveDeferred = async <T,>(deferred: Deferred<T>, value: T) =>
  resolveDeferred(deferred, value, SAVE_SUCCESS_DELAY_MS);

const actFlow = async (callback: () => Promise<void> | void) => {
  await act(async () => {
    await callback();
    await Promise.resolve();
  });
};

const waitForEditClosed = async () => {
  await waitFor(() => expect(screen.queryByRole('combobox')).not.toBeInTheDocument(), { timeout: 2000 });
};

const getSaveButton = () => screen.getByRole('button', { name: /save|merge with|assign to/i });

/* eslint-disable @typescript-eslint/require-await */
describe('IdentityClusterList', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    setupMocks();
    findClusterDeferreds = [];
    defaultFindClusterByLabel = vi.fn(() => {
      const deferred = createDeferred<ClusterLabelMatch | null>();
      findClusterDeferreds.push(deferred);
      return deferred.promise;
    });
    useClusterSuggestionsLoaderMock.mockReturnValue(
      loaderResultFrom({
        findClusterByLabel: defaultFindClusterByLabel,
      }),
    );
    vi.mocked(api.fetchIdentitiesSuggestions).mockResolvedValue({ matches: {} });
    vi.mocked(api.listRecognitionClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
    });
  });

  afterEach(async () => {
    // Cancel in-flight queries to prevent async leaks between tests
    if (activeQueryClient) {
      await activeQueryClient.cancelQueries();
      activeQueryClient.clear();
      activeQueryClient = null;
    }

    await actFlow(async () => {
      await resolveFindClusterDeferreds(null);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
      await Promise.resolve();
    });
    vi.useRealTimers();
    cleanup();
  });

  it('renders placeholder when no identities exist', async () => {
    await renderWithClient(<IdentityClusterList identities={[]} />);
    expect(screen.getByText(/No identities detected yet/i)).toBeInTheDocument();
    expect(MockEventSource.instances).toBe(0);
  });

  it('BR-46: list renders when labelMatches includes a null-label summary', async () => {
    useClusterSuggestionsLoaderMock.mockReturnValue(
      loaderResultFrom({
        labelMatches: [
          {
            id: 'null-labeled',
            label: null,
            identity_count: 1,
            member_ids: ['identity-x'],
            representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 100, height: 100 } },
            sample_identities: [],
          },
          {
            id: 'named',
            label: 'Pat Rivera',
            identity_count: 2,
            member_ids: ['identity-y'],
            representative_identity: { media_id: 2, bbox: { x: 0, y: 0, width: 100, height: 100 } },
            sample_identities: [],
          },
        ],
        findClusterByLabel: defaultFindClusterByLabel,
      }),
    );

    const { client } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);
    await actFlow(async () => {
      setMediaIdentitiesCache(client, {
        identities_by_media: {
          '1': [baseIdentity],
        },
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Cluster 1')).toBeInTheDocument();
    });
    const result = useClusterSuggestionsLoaderMock.mock.results.at(-1)?.value as ClusterSuggestionsLoaderResult;
    expect(result.namingOptions.some((option) => option.label === 'Pat Rivera')).toBe(true);
    expect(result.namingOptions.every((option) => option.label !== '')).toBe(true);
  });

  it('renders an unavailable warning when identity data cannot be loaded', async () => {
    const onRetry = vi.fn();
    const { user } = await renderWithClient(
      <IdentityClusterList identities={[]} dataSource={DATA_SOURCE.UNAVAILABLE} onRetry={onRetry} />,
    );

    expect(screen.getByText(/Identity data unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/could not load identities/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('S3-T6 a11y: unavailable affordance is a polite live region with named Retry control', async () => {
    const onRetry = vi.fn();
    await renderWithClient(
      <IdentityClusterList identities={[]} dataSource={DATA_SOURCE.UNAVAILABLE} onRetry={onRetry} />,
    );

    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent(/Identity data unavailable/i);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('BR-05: renders a distinct "reachable but erroring" warning for endpoint_error, not a confident empty', async () => {
    const onRetry = vi.fn();
    const { user } = await renderWithClient(
      <IdentityClusterList identities={[]} dataSource={DATA_SOURCE.ENDPOINT_ERROR} onRetry={onRetry} />,
    );

    expect(screen.getByText(/reachable but returned an error/i)).toBeInTheDocument();
    // Must NOT collapse a 5xx into the confident "none detected" state.
    expect(screen.queryByText(/No identities detected yet/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('BR-09: an empty local projection reads as "not synced yet", not a confident "none detected"', async () => {
    await renderWithClient(<IdentityClusterList identities={[]} dataSource={DATA_SOURCE.LOCAL_PROJECTION} />);

    expect(screen.getByText(/No identities synced for this item yet/i)).toBeInTheDocument();
    // The offline projection must not assert a final "analyzed, none found" result.
    expect(screen.queryByText(/No identities detected yet/i)).not.toBeInTheDocument();
  });

  it('keeps backend-fallback clusters labelable while hiding local-only corrective actions', async () => {
    await renderWithClient(<IdentityClusterList identities={[baseIdentity]} dataSource={DATA_SOURCE.BACKEND_PROXY} />);

    expect(
      screen.getByText('Names can be curated now. Split/remove actions stay disabled until local sync completes.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cluster 1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Name this person|Edit label/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Remove from group/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Split group/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Pin representative|Unpin representative/i })).not.toBeInTheDocument();
  });

  it('does not render pin plumbing on the cluster preview (UXA-07)', async () => {
    const pinRepresentativeMock = vi.mocked(api.pinRepresentative);
    pinRepresentativeMock.mockResolvedValue(undefined);

    const { client } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);

    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [
          {
            ...baseIdentity,
            is_pinned: true,
          },
        ],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    expect(screen.queryByRole('button', { name: /pin representative/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /unpin representative/i })).not.toBeInTheDocument();
    expect(pinRepresentativeMock).not.toHaveBeenCalled();
  });

  it('allows renaming a manually labeled cluster', async () => {
    const updateDeferred = createDeferred<unknown>();
    (api.updateClusterLabel as Mock).mockReturnValue(updateDeferred.promise);
    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);

    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [
          {
            ...baseIdentity,
          },
        ],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })));
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'New Label' } });
    });
    expect(input).toHaveValue('New Label');

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()));
      await resolveFindClusterDeferreds(null);
      await resolveSaveDeferred(updateDeferred, {});
    });

    await waitForEditClosed();

    await waitFor(() =>
      expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-1', 'New Label', expect.anything()),
    );

    const updated = client.getQueryData<MediaIdentitiesResponse>(queryKeys.media.identitiesByIds([1]));
    expect(updated?.identities_by_media['1'][0].cluster_label).toBe('New Label');
    expect(updated?.identities_by_media['1'][0].is_auto_label).toBe(false);
  });

  it('renames auto-labeled clusters to new label', async () => {
    const updateDeferred = createDeferred<unknown>();
    (api.updateClusterLabel as Mock).mockReturnValue(updateDeferred.promise);
    const autoIdentity = {
      ...baseIdentity,
      id: 'auto-1',
      cluster_id: 'cluster-auto',
      cluster_label: 'cluster-auto',
      is_auto_label: true,
    };

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[autoIdentity]} />);

    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [
          {
            ...autoIdentity,
          },
        ],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /Name this person/i })));
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'Person A' } });
    });
    expect(input).toHaveValue('Person A');

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()));
      await resolveFindClusterDeferreds(null);
      await resolveSaveDeferred(updateDeferred, {});
    });

    await waitForEditClosed();

    await waitFor(() =>
      expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-auto', 'Person A', expect.anything()),
    );

    const updated = client.getQueryData<MediaIdentitiesResponse>(queryKeys.media.identitiesByIds([1]));
    expect(updated?.identities_by_media['1'][0].cluster_label).toBe('Person A');
    expect(updated?.identities_by_media['1'][0].is_auto_label).toBe(false);
  });

  it('shows identity suggestions in the overlay', async () => {
    useClusterSuggestionsLoaderMock.mockReturnValue(
      loaderResultFrom({
        identityProjection: [
          {
            identityId: baseIdentity.identity_id,
            clusterId: 'cluster-suggested',
            label: 'Ada Lovelace',
            similarity: 0.92,
            identityCount: 3,
          },
        ],
        findClusterByLabel: defaultFindClusterByLabel,
      }),
    );

    const { user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })));
    });
    const input = screen.getByRole('combobox');
    await actFlow(async () => {
      await runWithTimers(() => {
        fireEvent.change(input, { target: { value: 'Ada' } });
      });
      await resolveFindClusterDeferreds(null);
    });

    expect(screen.getByRole('option', { name: /Ada Lovelace \(Group\)/ })).toBeInTheDocument();
    await actFlow(async () => {
      await user.click(screen.getByRole('button', { name: /cancel/i }));
    });
    await waitForEditClosed();
  });

  it('uses search to find cluster by label when saving to an existing label', async () => {
    const existingCluster = { id: 'cluster-500', label: 'Hazel McCleod', identity_count: 1 };
    const matchDeferreds: Deferred<ClusterLabelMatch | null>[] = [];
    const findClusterByLabelRemote = vi.fn(() => {
      const deferred = createDeferred<ClusterLabelMatch | null>();
      matchDeferreds.push(deferred);
      return deferred.promise;
    });

    useClusterSuggestionsLoaderMock.mockReturnValue(
      loaderResultFrom({
        findClusterByLabel: findClusterByLabelRemote,
      }),
    );

    const mergeDeferred = createDeferred<unknown>();
    (api.mergeCluster as Mock).mockReturnValue(mergeDeferred.promise);
    const mergeResult = {
      source_id: 'cluster-1',
      source_label: 'Cluster 1',
      target_id: 'cluster-500',
      target_label: 'Hazel McCleod',
      identities_moved: 1,
      moved_identity_ids: ['identity-1'],
      target_identity_count: 2,
    };

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })));
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      fireEvent.change(input, { target: { value: 'Hazel McCleod' } });
    });
    expect(input).toHaveValue('Hazel McCleod');

    await actFlow(async () => {
      // Wait for debounce timer to trigger remote search
      await flushTimers(MATCH_DEBOUNCE_MS);
    });
    await waitFor(() => expect(findClusterByLabelRemote).toHaveBeenCalled());
    const matchDeferred = matchDeferreds[0];
    expect(matchDeferred).toBeDefined();
    await actFlow(async () => {
      if (!matchDeferred) {
        throw new Error('Expected match deferred to be defined.');
      }
      await resolveDeferred(matchDeferred, {
        id: existingCluster.id,
        label: existingCluster.label,
        identityCount: existingCluster.identity_count,
      });
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()));
      await resolveSaveDeferred(mergeDeferred, mergeResult);
    });
    await waitFor(() => expect(findClusterByLabelRemote).toHaveBeenCalled());
    await waitForEditClosed();

    // No merge modal expected since identityCount is 1 (< 5)

    await waitFor(() =>
      expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'cluster-500', 'Hazel McCleod', expect.anything()),
    );
  });

  it('treats a self-match returned by label lookup as a rename', async () => {
    const updateDeferred = createDeferred<unknown>();
    (api.updateClusterLabel as Mock).mockReturnValue(updateDeferred.promise);

    const matchDeferreds: Deferred<ClusterLabelMatch | null>[] = [];
    const findClusterByLabelRemote = vi.fn(() => {
      const deferred = createDeferred<ClusterLabelMatch | null>();
      matchDeferreds.push(deferred);
      return deferred.promise;
    });

    useClusterSuggestionsLoaderMock.mockReturnValue(
      loaderResultFrom({
        findClusterByLabel: findClusterByLabelRemote,
      }),
    );

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })));
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'Saffron Cypress' } });
    });

    await actFlow(async () => {
      await flushTimers(MATCH_DEBOUNCE_MS);
    });
    await waitFor(() => expect(findClusterByLabelRemote).toHaveBeenCalled());

    const matchDeferred = matchDeferreds[0];
    expect(matchDeferred).toBeDefined();
    await actFlow(async () => {
      if (!matchDeferred) {
        throw new Error('Expected self-match deferred to be defined.');
      }
      await resolveDeferred(matchDeferred, { id: 'cluster-1', label: 'Saffron Cypress' });
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()));
    });
    await waitFor(() => expect(findClusterByLabelRemote).toHaveBeenCalledTimes(2));

    const saveMatchDeferred = matchDeferreds[1];
    expect(saveMatchDeferred).toBeDefined();
    await actFlow(async () => {
      if (!saveMatchDeferred) {
        throw new Error('Expected save-time self-match deferred to be defined.');
      }
      await resolveDeferred(saveMatchDeferred, { id: 'cluster-1', label: 'Saffron Cypress' });
      await resolveSaveDeferred(updateDeferred, {});
    });

    await waitForEditClosed();

    await waitFor(() =>
      expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-1', 'Saffron Cypress', expect.anything()),
    );
    expect(api.mergeCluster).not.toHaveBeenCalled();
  });

  it('merges into existing cluster when label matches', async () => {
    const mergeDeferred = createDeferred<unknown>();
    (api.mergeCluster as Mock).mockReturnValue(mergeDeferred.promise);
    const mergeResult = {
      source_id: 'cluster-1',
      source_label: 'Cluster 1',
      target_id: 'target-cluster',
      target_label: 'Existing Label',
      identities_moved: 1,
      moved_identity_ids: ['identity-1'],
      target_identity_count: 2,
    };
    const existingClusters = [
      {
        id: 'target-cluster',
        label: 'Existing Label',
        identity_count: 1,
        member_ids: ['identity-1'],
        representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 100, height: 100 } },
        sample_identities: [],
      },
    ];
    useClusterSuggestionsLoaderMock.mockReturnValue(
      loaderResultFrom({
        labelMatches: existingClusters,
        findClusterByLabel: defaultFindClusterByLabel,
      }),
    );

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);

    // ... setup cache ...
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    // Wait for edit button to appear before clicking
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })));
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'Existing Label' } });
    });
    expect(input).toHaveValue('Existing Label');

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()));
      await resolveSaveDeferred(mergeDeferred, mergeResult);
    });
    await waitForEditClosed();

    // No merge modal expected since identity_count is 1 (< 5)

    await waitFor(() =>
      expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'target-cluster', 'Existing Label', expect.anything()),
    );
  });

  it('shows a friendly inline message when merge rejects a self-target request', async () => {
    (api.mergeCluster as Mock).mockRejectedValueOnce(
      new Error(
        'Request to /recognition/clusters/cluster-1/merge failed (400): {"code":"invalid_target_cluster_id","message":"Source and target cluster IDs must differ."}',
      ),
    );
    const existingClusters = [
      {
        id: 'target-cluster',
        label: 'Existing Label',
        identity_count: 1,
        member_ids: ['identity-1'],
        representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 100, height: 100 } },
        sample_identities: [],
      },
    ];
    useClusterSuggestionsLoaderMock.mockReturnValue(
      loaderResultFrom({
        labelMatches: existingClusters,
        findClusterByLabel: defaultFindClusterByLabel,
      }),
    );

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })));
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'Existing Label' } });
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()));
    });

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'That group is already named Existing Label - nothing to merge.',
      );
    });
  });

  it('shows undo when merge completes and reverts on request', async () => {
    const mergeDeferred = createDeferred<unknown>();
    const revertDeferred = createDeferred<unknown>();
    (api.mergeCluster as Mock).mockReturnValue(mergeDeferred.promise);
    (api.revertMergeCluster as Mock).mockReturnValue(revertDeferred.promise);
    const mergeResult = {
      source_id: 'cluster-1',
      source_label: 'Cluster 1',
      target_id: 'target-cluster',
      target_label: 'Existing Label',
      identities_moved: 1,
      moved_identity_ids: ['identity-1'],
      target_identity_count: 2,
    };
    const revertResult = {
      restored_cluster_id: 'restored-1',
      restored_label: 'Cluster 1',
      restored_identity_count: 1,
      target_cluster_id: 'target-cluster',
      target_identity_count: 1,
    };
    const existingClusters = [
      {
        id: 'target-cluster',
        label: 'Existing Label',
        identity_count: 1,
        member_ids: ['identity-1'],
        representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 100, height: 100 } },
        sample_identities: [],
      },
    ];
    useClusterSuggestionsLoaderMock.mockReturnValue(
      loaderResultFrom({
        labelMatches: existingClusters,
        findClusterByLabel: defaultFindClusterByLabel,
      }),
    );

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    // Wait for edit button to appear before clicking
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })));
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'Existing Label' } });
    });
    expect(input).toHaveValue('Existing Label');

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()));
      await resolveSaveDeferred(mergeDeferred, mergeResult);
    });
    await waitForEditClosed();

    // No merge modal expected since identity_count is 1 (< 5)

    await waitFor(() =>
      expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'target-cluster', 'Existing Label', expect.anything()),
    );

    const undoButton = screen.getByRole('button', { name: /Undo merge/i });
    await actFlow(async () => {
      await user.click(undoButton);
      await resolveDeferred(revertDeferred, revertResult);
    });

    await waitFor(() =>
      expect(api.revertMergeCluster).toHaveBeenCalledWith({
        targetClusterId: 'target-cluster',
        movedIdentityIds: ['identity-1'],
        sourceLabel: 'Cluster 1',
      }),
    );
    await waitFor(() => expect(screen.queryByRole('button', { name: /undo merge/i })).not.toBeInTheDocument(), {
      timeout: 2000,
    });
  });

  it('renders face thumbnail when media_url is provided', async () => {
    const identityWithMediaUrl = {
      ...baseIdentity,
      media_url: 'https://example.com/photo.jpg',
    };

    const { client } = await renderWithClient(<IdentityClusterList identities={[identityWithMediaUrl]} />);
    // Set cache to trigger re-render with identity data
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [identityWithMediaUrl],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await waitFor(() => {
      const image = screen.getByRole('img', { name: /detected identity thumbnail/i });
      expect(image).toHaveAttribute('src', 'https://example.com/photo.jpg');
    });
  });

  it('allows clicking the unlabeled text to start editing', async () => {
    const unlabeled = {
      ...baseIdentity,
      cluster_label: null,
    };
    const { client, user } = await renderWithClient(<IdentityClusterList identities={[unlabeled]} />);
    // Set cache to ensure component renders with data
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [unlabeled],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    // Wait for the unlabeled button to appear and click it
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Unnamed person/i })).toBeInTheDocument();
    });
    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /Unnamed person/i })));
    });
    expect(screen.getByRole('combobox')).toBeInTheDocument();
    await actFlow(async () => {
      await user.click(screen.getByRole('button', { name: /cancel/i }));
    });
    await waitForEditClosed();
  });

  it('allows unlinking an identity (wrong person) only for singletons', async () => {
    const reassignDeferred = createDeferred<unknown>();
    (api.reassignClusterIdentity as Mock).mockReturnValue(reassignDeferred.promise);

    // 1. Singleton case - button should be visible
    const { client, user, unmount } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    // Wait for button to appear
    await waitFor(() => {
      expect(screen.getByText('Remove from group', { selector: 'button' })).toBeInTheDocument();
    });

    const wrongPersonButton = screen.getByText('Remove from group', { selector: 'button' });
    await actFlow(async () => {
      await user.click(wrongPersonButton);
    });

    await screen.findByRole('dialog');

    await actFlow(async () => {
      await user.click(screen.getByRole('button', { name: /remove member/i }));
    });

    await actFlow(async () => {
      await resolveDeferred(reassignDeferred, {});
    });
    await waitFor(() =>
      expect(api.reassignClusterIdentity).toHaveBeenCalledWith({
        identityId: 'identity-1',
        targetClusterId: null,
        blockFromCluster: true,
      }),
    );
    unmount();

    // 2. Multi-member case - button should be hidden
    const member1 = { ...baseIdentity, identity_id: '1', cluster_id: 'c1', cluster_label: 'Startrek' };
    const member2 = { ...baseIdentity, identity_id: '2', cluster_id: 'c1', cluster_label: 'Startrek' };

    await renderWithClient(<IdentityClusterList identities={[member1, member2]} />);

    expect(screen.queryByRole('button', { name: /remove from group/i })).not.toBeInTheDocument();
  });

  it('allows splitting a cluster', async () => {
    const splitDeferred = createDeferred<unknown>();
    (api.splitCluster as Mock).mockReturnValue(splitDeferred.promise);

    const secondIdentity = {
      ...baseIdentity,
      identity_id: 'identity-2',
      media_id: 2,
    };

    const { client, user } = await renderWithClient(
      <IdentityClusterList identities={[baseIdentity, secondIdentity]} />,
    );
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity, secondIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    // Wait for split button to appear
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /split group/i })).toBeInTheDocument();
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /split group/i })));
    });

    await screen.findByRole('dialog');
    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /use face from media #1/i })));
      await resolveDeferred(splitDeferred, { moved_count: 5 });
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    // Split always forces 2 clusters to guarantee a split happens
    await waitFor(() =>
      expect(api.splitCluster).toHaveBeenCalledWith('cluster-1', {
        nClusters: 2,
        anchorIdentityId: 'identity-1',
        splitMode: 'forced',
        mode: 'sync',
      }),
    );
  });

  describe('inline suggestion batching', () => {
    const makeUnlabeled = (count: number) =>
      Array.from({ length: count }, (_, i) => ({
        ...baseIdentity,
        identity_id: `id-${i}`,
        media_id: i + 1,
        cluster_id: null,
        cluster_label: null,
      }));

    it('issues exactly one batched suggestions fetch at projection depth for N unlabeled cards', async () => {
      const identities = makeUnlabeled(5);
      await renderWithClient(<IdentityClusterList identities={identities} />);

      await waitFor(() => expect(api.fetchIdentitiesSuggestions).toHaveBeenCalledTimes(1));
      expect(api.fetchIdentitiesSuggestions).toHaveBeenCalledWith(['id-0', 'id-1', 'id-2', 'id-3', 'id-4'], 5);
    });

    it('fetches no suggestions in label-only mode (zero fetches)', async () => {
      const identities = makeUnlabeled(3);
      await renderWithClient(<IdentityClusterList identities={identities} dataSource={DATA_SOURCE.BACKEND_PROXY} />);

      await flushTimers();
      expect(api.fetchIdentitiesSuggestions).not.toHaveBeenCalled();
    });

    it('resolves an inline prompt on every one of 60 unlabeled cards from a single batch', async () => {
      const identities = makeUnlabeled(60);
      // Several identities carry >=2 pending suggestions (guards the row-vs-identity
      // bound); the client keys by identity id and takes the first server-ranked match.
      const matches = Object.fromEntries(
        identities.map((identity, i) => {
          const primary = { cluster_id: `c-${i}`, label: `Person ${i}`, similarity: 0.9, identity_count: 2 };
          const rows =
            i % 4 === 0
              ? [primary, { cluster_id: `c-${i}-b`, label: `Person ${i} alt`, similarity: 0.8, identity_count: 1 }]
              : [primary];
          return [identity.identity_id, rows];
        }),
      );
      vi.mocked(api.fetchIdentitiesSuggestions).mockResolvedValue({ matches });

      await renderWithClient(<IdentityClusterList identities={identities} />);

      await waitFor(() => expect(screen.getAllByRole('button', { name: 'Yes' })).toHaveLength(60));
      expect(api.fetchIdentitiesSuggestions).toHaveBeenCalledTimes(1);
      // First (server-ranked) match is the one shown, even where >=2 rows exist.
      expect(screen.getByText('Person 0')).toBeInTheDocument();
      expect(screen.queryByText('Person 0 alt')).not.toBeInTheDocument();
    });

    it('renders nothing for an identity absent from the keyed envelope (empty-match)', async () => {
      const identities = makeUnlabeled(2);
      vi.mocked(api.fetchIdentitiesSuggestions).mockResolvedValue({
        matches: { 'id-0': [{ cluster_id: 'c-0', label: 'Ada', similarity: 0.9, identity_count: 2 }] },
      });

      await renderWithClient(<IdentityClusterList identities={identities} />);

      await waitFor(() => expect(screen.getByText('Ada')).toBeInTheDocument());
      // 'id-1' had no eligible suggestion → exactly one prompt renders.
      expect(screen.getAllByRole('button', { name: 'Yes' })).toHaveLength(1);
    });
  });
});
