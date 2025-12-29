import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { IdentityClusterList } from '../identity-clusters';
import * as api from '../../../api/recognition';
import type { MediaIdentitiesResponse } from '../../../api/recognition';
import type {
  ClusterSuggestionsLoaderOptions,
  ClusterSuggestionsLoaderResult,
} from '../identity-clusters/useClusterSuggestionsLoader';

const useClusterSuggestionsLoaderMock = vi.hoisted(
  () => vi.fn<ClusterSuggestionsLoaderResult, [ClusterSuggestionsLoaderOptions]>(),
);

let defaultFindClusterByLabel: ReturnType<typeof vi.fn>;
let findClusterDeferreds: Deferred<{ id: string; label: string } | null>[] = [];

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

// Mock EventSource for useClusterEvents
class MockEventSource {
  onmessage: any = null;
  onerror: any = null;
  close = vi.fn();
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  constructor(_url: string) {}
}

const setupMocks = () => {
  // Mock AltContextAdmin config
  (window as any).AltContextAdmin = {
    nonce: 'test-nonce',
    endpoints: {
      recognition: 'http://localhost:8000',
      recognitionClusters: 'http://localhost:8000/clusters',
      workbenchFaceClusters: 'http://localhost:8000/clusters',
      workbenchRecognitionClusters: 'http://localhost:8000/clusters',
      workbenchRecognitionReassignIdentity: 'http://localhost:8000/reassign-identity',
      recognitionRevertMerge: 'http://localhost:8000/revert-merge',
      workbenchRecognitionRevertMerge: 'http://localhost:8000/revert-merge',
      workbenchRecognitionCreateClusterForIdentity: 'http://localhost:8000/create-for-identity',
      recognitionFaceSuggestions: 'http://localhost:8000/suggestions',
      workbenchRecognitionFaceSuggestions: 'http://localhost:8000/suggestions',
    },
    tenant_id: 'test-tenant',
  };

  window.EventSource = MockEventSource as any;
};

vi.mock('../identity-clusters/useClusterSuggestionsLoader', () => ({
  useClusterSuggestionsLoader: (options: ClusterSuggestionsLoaderOptions) => useClusterSuggestionsLoaderMock(options),
}));

vi.mock('../../../api/recognition', () => ({
  mergeCluster: vi.fn(),
  updateClusterLabel: vi.fn(),
  fetchIdentitySuggestions: vi.fn(),
  listRecognitionClusters: vi.fn(),
  revertMergeCluster: vi.fn(),
  reassignClusterIdentity: vi.fn(),
  splitCluster: vi.fn(),
}));

const renderWithClient = async (ui: React.ReactElement) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup({
    advanceTimers: async (ms: number) => {
      await vi.advanceTimersByTimeAsync(ms);
    },
  });
  const utils = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { client, user, ...utils };
};

const setMediaIdentitiesCache = (client: QueryClient, data: MediaIdentitiesResponse) => {
  client.setQueryData(['media-identities', [1]], data);
};

const baseIdentity = {
  identity_id: 'identity-1',
  media_id: 1,
  cluster_id: 'cluster-1',
  cluster_label: 'Cluster 1',
  is_auto_label: false,
  bbox: { x: 0, y: 0, width: 10, height: 10 },
  confidence: 0.9,
  similarity: 0.9,
  detected_at: '',
  thumbnail_url: null,
};

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

const SAVE_SUCCESS_DELAY_MS = 1200;

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const resolveDeferred = async <T,>(deferred: Deferred<T>, value: T, advanceMs = 0) => {
  deferred.resolve(value);
  await deferred.promise;
  if (advanceMs > 0) {
    await vi.advanceTimersByTimeAsync(advanceMs);
  }
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
};

const resolveFindClusterDeferreds = async (value: { id: string; label: string } | null) => {
  while (findClusterDeferreds.length > 0) {
    const deferred = findClusterDeferreds.shift();
    if (deferred) {
      await resolveDeferred(deferred, value);
    }
  }
};

const runWithTimers = async (callback: () => Promise<void> | void, ms: number) => {
  await callback();
  if (ms > 0) {
    await vi.advanceTimersByTimeAsync(ms);
  }
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
};

const actFlow = async (callback: () => Promise<void> | void) => {
  await act(async () => {
    await callback();
    await Promise.resolve();
  });
};

const waitForEditClosed = async () => {
  await waitFor(
    () => expect(screen.queryByRole('combobox')).not.toBeInTheDocument(),
    { timeout: 2000 },
  );
};

const getSaveButton = () => screen.getByRole('button', { name: /save|merge with|assign to/i });

describe('IdentityClusterList', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    setupMocks();
    findClusterDeferreds = [];
    defaultFindClusterByLabel = vi.fn(() => {
      const deferred = createDeferred<{ id: string; label: string } | null>();
      findClusterDeferreds.push(deferred);
      return deferred.promise;
    });
    useClusterSuggestionsLoaderMock.mockReturnValue({
      identitySuggestions: { matches: [] },
      labelMatches: [],
      isLoading: false,
      findClusterByLabel: defaultFindClusterByLabel,
    });
    vi.mocked(api.fetchIdentitySuggestions).mockResolvedValue({ matches: [] });
    vi.mocked(api.listRecognitionClusters).mockResolvedValue([]);
  });

  afterEach(async () => {
    await actFlow(async () => {
      await resolveFindClusterDeferreds(null);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
      await Promise.resolve();
    });
    vi.useRealTimers();
  });

  it('renders placeholder when no identities exist', async () => {
    await renderWithClient(<IdentityClusterList identities={[]} mediaId={1} />);
    expect(screen.getByText(/No identities detected yet/i)).toBeInTheDocument();
  });

  it('allows renaming a manually labeled cluster', async () => {
    const updateDeferred = createDeferred<unknown>();
    (api.updateClusterLabel as Mock).mockReturnValue(updateDeferred.promise);
    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);

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
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })), 0);
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'New Label' } });
    });
    expect(input).toHaveValue('New Label');

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()), 1300);
      await resolveFindClusterDeferreds(null);
      await resolveDeferred(updateDeferred, {}, SAVE_SUCCESS_DELAY_MS);
    });

    await waitForEditClosed();

    await waitFor(() =>
      expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-1', 'New Label', expect.anything()),
    );

    const updated = client.getQueryData<MediaIdentitiesResponse>(['media-identities', [1]]);
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

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[autoIdentity]} mediaId={1} />);

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
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /Name this person/i })), 0);
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'Person A' } });
    });
    expect(input).toHaveValue('Person A');

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()), 1300);
      await resolveFindClusterDeferreds(null);
      await resolveDeferred(updateDeferred, {}, SAVE_SUCCESS_DELAY_MS);
    });

    await waitForEditClosed();

    await waitFor(() =>
      expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-auto', 'Person A', expect.anything()),
    );

    const updated = client.getQueryData<MediaIdentitiesResponse>(['media-identities', [1]]);
    expect(updated?.identities_by_media['1'][0].cluster_label).toBe('Person A');
    expect(updated?.identities_by_media['1'][0].is_auto_label).toBe(false);
  });

  it('shows identity suggestions in the overlay', async () => {
    const loaderResult = {
      identitySuggestions: {
        matches: [
          {
            cluster_id: 'cluster-suggested',
            label: 'Ada Lovelace',
            similarity: 0.92,
            identity_count: 3,
          },
        ],
      },
      labelMatches: [],
      isLoading: false,
      findClusterByLabel: defaultFindClusterByLabel,
    };
    useClusterSuggestionsLoaderMock.mockReturnValue(loaderResult);

    const { user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })), 0);
    });
    const input = screen.getByRole('combobox');
    await actFlow(async () => {
      await runWithTimers(() => {
        fireEvent.change(input, { target: { value: 'Ada' } });
      }, 350);
      await resolveFindClusterDeferreds(null);
    });

    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    await actFlow(async () => {
      await user.click(screen.getByRole('button', { name: /cancel/i }));
    });
    await waitForEditClosed();
  });

  it('uses search to find cluster by label when saving to an existing label', async () => {
    const existingCluster = { id: 'cluster-500', label: 'Erin McCleod', identity_count: 1 };
    const matchDeferreds: Deferred<{ id: string; label: string } | null>[] = [];
    const findClusterByLabelRemote = vi.fn(() => {
      const deferred = createDeferred<{ id: string; label: string } | null>();
      matchDeferreds.push(deferred);
      return deferred.promise;
    });

    const loaderResult = {
      identitySuggestions: { matches: [] },
      labelMatches: [],
      isLoading: false,
      findClusterByLabel: findClusterByLabelRemote,
    };
    useClusterSuggestionsLoaderMock.mockReturnValue(loaderResult);

    const mergeDeferred = createDeferred<unknown>();
    (api.mergeCluster as Mock).mockReturnValue(mergeDeferred.promise);
    const mergeResult = {
      source_id: 'cluster-1',
      source_label: 'Cluster 1',
      target_id: 'cluster-500',
      target_label: 'Erin McCleod',
      identities_moved: 1,
      moved_identity_ids: ['identity-1'],
      target_identity_count: 2,
    };

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })), 0);
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      fireEvent.change(input, { target: { value: 'Erin McCleod' } });
    });
    expect(input).toHaveValue('Erin McCleod');

    await actFlow(async () => {
      await runWithTimers(() => {}, 350);
      await resolveDeferred(matchDeferreds[0], { id: existingCluster.id, label: existingCluster.label });
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()), 1300);
      await resolveDeferred(mergeDeferred, mergeResult, SAVE_SUCCESS_DELAY_MS);
    });
    await waitFor(() => expect(findClusterByLabelRemote).toHaveBeenCalled());
    await waitForEditClosed();

    // No merge modal expected since identity_count is 1 (< 5)

    await waitFor(() =>
      expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'cluster-500', 'Erin McCleod', expect.anything()),
    );
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
    const existingClusters = [{ id: 'target-cluster', label: 'Existing Label', identity_count: 1 }];
    const loaderResult = {
      identitySuggestions: { matches: [] },
      labelMatches: existingClusters,
      isLoading: false,
      findClusterByLabel: defaultFindClusterByLabel,
    };
    useClusterSuggestionsLoaderMock.mockReturnValue(loaderResult);

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);

    // ... setup cache ...
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })), 0);
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'Existing Label' } });
    });
    expect(input).toHaveValue('Existing Label');

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()), 1300);
      await resolveDeferred(mergeDeferred, mergeResult, SAVE_SUCCESS_DELAY_MS);
    });
    await waitForEditClosed();

    // No merge modal expected since identity_count is 1 (< 5)

    await waitFor(() =>
      expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'target-cluster', 'Existing Label', expect.anything()),
    );
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
    const existingClusters = [{ id: 'target-cluster', label: 'Existing Label', identity_count: 1 }];
    const loaderResult = {
      identitySuggestions: { matches: [] },
      labelMatches: existingClusters,
      isLoading: false,
      findClusterByLabel: defaultFindClusterByLabel,
    };
    useClusterSuggestionsLoaderMock.mockReturnValue(loaderResult);

    const { client, user } = await renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
    });

    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /edit label/i })), 0);
    });
    const input = screen.getByPlaceholderText(/enter a name/i);
    await actFlow(async () => {
      await user.clear(input);
      fireEvent.change(input, { target: { value: 'Existing Label' } });
    });
    expect(input).toHaveValue('Existing Label');

    await actFlow(async () => {
      await runWithTimers(() => user.click(getSaveButton()), 1300);
      await resolveDeferred(mergeDeferred, mergeResult, SAVE_SUCCESS_DELAY_MS);
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
    await waitFor(
      () => expect(screen.queryByRole('button', { name: /undo merge/i })).not.toBeInTheDocument(),
      { timeout: 2000 },
    );
  });

  it('renders face thumbnail when media_url is provided', async () => {
    const identityWithMediaUrl = {
      ...baseIdentity,
      media_url: 'https://example.com/photo.jpg',
    };

    await renderWithClient(<IdentityClusterList identities={[identityWithMediaUrl]} mediaId={1} />);
    const image = screen.getByRole('img', { name: /detected identity thumbnail/i });
    expect(image).toHaveAttribute('src', 'https://example.com/photo.jpg');
  });

  it('allows clicking the unlabeled text to start editing', async () => {
    const unlabeled = {
      ...baseIdentity,
      cluster_label: null,
    };
    const { user } = await renderWithClient(<IdentityClusterList identities={[unlabeled]} mediaId={1} />);
    await actFlow(async () => {
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /cluster-clust/i })), 350);
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
    vi.spyOn(window, 'confirm').mockImplementation(() => true);

    // 1. Singleton case - button should be visible
    const { client, user, unmount } = await renderWithClient(
      <IdentityClusterList identities={[baseIdentity]} mediaId={1} />,
    );
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);

      const wrongPersonButton = screen.getByText('Remove from Cluster', { selector: 'button' });
      expect(wrongPersonButton).toBeInTheDocument();

      await user.click(wrongPersonButton);
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

    await renderWithClient(<IdentityClusterList identities={[member1, member2]} mediaId={1} />);

    expect(screen.queryByRole('button', { name: /remove from cluster/i })).not.toBeInTheDocument();
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
      <IdentityClusterList identities={[baseIdentity, secondIdentity]} mediaId={1} />,
    );
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity, secondIdentity],
      },
    };
    await actFlow(async () => {
      setMediaIdentitiesCache(client, cacheData);
      await runWithTimers(() => user.click(screen.getByRole('button', { name: /split cluster/i })), 50);
    });

    await screen.findByRole('dialog');
    await actFlow(async () => {
      await runWithTimers(
        () => user.click(screen.getByRole('button', { name: /use face from media #1/i })),
        50,
      );
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
});
