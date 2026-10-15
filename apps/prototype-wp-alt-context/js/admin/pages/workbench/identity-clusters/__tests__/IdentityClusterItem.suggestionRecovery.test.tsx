import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import type { DetectedIdentity } from '../../../../api/recognition';
import type { ComboboxOption } from '../../../../../components/ui/combobox';
import { namingOptionValue } from '../buildNamingOptions';
import { useClusterSuggestions } from '../useClusterSuggestions';
import { IdentityClusterItem } from '../IdentityClusterItem';

vi.mock('../useClusterSuggestions', () => ({ useClusterSuggestions: vi.fn() }));
vi.mock('../useClusterMutations', () => ({
  useClusterMutations: () => ({
    isPending: false,
    isReverting: false,
    merge: vi.fn(),
    assignToCluster: vi.fn(),
    rename: vi.fn(),
    createClusterForIdentity: vi.fn(),
    reassign: vi.fn(),
    split: vi.fn(),
    revertMerge: vi.fn(),
    rejectSuggestion: vi.fn(),
    splitGate: { disabled: false, title: undefined, 'aria-disabled': false },
  }),
}));


const cachedChoice: ComboboxOption = {
  value: namingOptionValue('person', 7),
  label: 'Ellyn Heald',
  source: 'person',
  group: 'Suggested',
  band: 'none',
  roster_entry_id: 7,
  cluster_id: 'cluster-ellyn',
};
const member: DetectedIdentity = {
  identity_id: 'identity-unnamed',
  representative_id: 'rep-1',
  media_id: 1,
  cluster_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  cluster_label: null,
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 1,
  detected_at: '',
};

let client: QueryClient;
let healthy = false;
const failedRead = vi.fn<() => Promise<ComboboxOption[]>>();
const retry = vi.fn<() => void>();
const findClusterByLabel = vi.fn().mockResolvedValue(null);

// Keep the consumer boundary mocked as in the existing suites, but let real
// React Query retain a cached choice when the read fails and drive retry state.
const useSuggestionFixture = ({ enabled }: Parameters<typeof useClusterSuggestions>[0]) => {
  const query = useQuery({
    queryKey: ['suggestion-recovery-fixture'],
    queryFn: failedRead,
    enabled,
    initialData: [cachedChoice],
    retry: false,
  });
  retry.mockImplementation(() => { void query.refetch(); });
  return {
    options: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    retry,
    collisionsByLabel: new Map(),
    findClusterByLabel,
    atRestTotal: 0,
    atRestTruncated: false,
    isAtRestMode: true,
  };
};

const renderConsumer = () => render(
  <QueryClientProvider client={client}>
    <IdentityClusterItem cluster={{
      key: member.cluster_id!, clusterId: member.cluster_id, label: null,
      isAutoLabel: false, clusteringPending: false, members: [member],
    }} canLabel canMutate />
  </QueryClientProvider>,
);
const openEditor = () => fireEvent.click(screen.getByRole('button', { name: 'Unnamed person' }));
const showCachedChoice = () => {
  fireEvent.keyDown(screen.getByRole('combobox', { name: 'Person name' }), { key: 'ArrowDown' });
  expect(screen.getByRole('option', { name: /Ellyn Heald/ })).toHaveTextContent('Below match threshold');
};
const awaitFailedRead = async () => {
  await waitFor(() => expect(client.getQueryState(['suggestion-recovery-fixture'])?.status).toBe('error'));
  expect(failedRead).toHaveBeenCalledTimes(1);
};

beforeEach(() => {
  vi.clearAllMocks();
  healthy = false;
  registerConfig({
    nonce: 'fixture-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: { recognitionClusters: '/wp-json/acx/v1/recognition/clusters' },
  });
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  failedRead.mockImplementation(() => {
    if (!healthy) return Promise.reject(new Error('Suggestion read unavailable (503 fixture)'));
    return Promise.resolve([cachedChoice]);
  });
  vi.mocked(useClusterSuggestions).mockImplementation(useSuggestionFixture);
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  client.clear();
  resetConfigCache();
});

describe('IdentityClusterItem legacy suggestion recovery (F3)', () => {
  it('F3-error: expanded editor shows a visible suggestion alert while cached choices remain available', async () => {
    renderConsumer();
    openEditor();
    await awaitFailedRead();
    showCachedChoice();

    const alert = screen.getByRole('alert');
    expect(alert).toBeVisible();
    expect(alert).toHaveTextContent('Could not load name suggestions.');
    expect(within(alert).getByRole('button', { name: 'Retry' })).toBeVisible();
  });

  it('F3-retry: clicking Retry reissues the failed read without removing the cached option', async () => {
    renderConsumer();
    openEditor();
    await awaitFailedRead();
    showCachedChoice();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(failedRead).toHaveBeenCalledTimes(2));
    showCachedChoice();
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load name suggestions.');
  });

  it('F3-healthy: healthy expanded editor shows cached choices without an error or Retry', async () => {
    healthy = true;
    renderConsumer();
    openEditor();
    await waitFor(() => expect(failedRead).toHaveBeenCalledTimes(1));
    showCachedChoice();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(retry).not.toHaveBeenCalled();
  });

  it('F3-collapsed: collapsed row spends no naming-read budget and renders no naming error', () => {
    renderConsumer();
    expect(screen.getByRole('button', { name: 'Unnamed person' })).toBeVisible();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(failedRead).not.toHaveBeenCalled();
    expect(retry).not.toHaveBeenCalled();
  });
});
