import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, cleanup, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ScanTabContent } from '../../../ScanTabContent';
import { dropClusterFromReviewCaches, REVIEW_DROP_MODE } from '../../suggestionProjection';
import { MergeSurvivorProvider } from '../../MergeSurvivorContext';
import { fetchPendingNameSuggestions } from '../../../../../api/recognition';
import { resetConfigCache } from '../../../../../api/config';
import { fetchRequiredApi } from '../../../../../utils/http';

vi.mock('../../../../../utils/http', async () => ({
  ...(await vi.importActual<typeof import('../../../../../utils/http')>('../../../../../utils/http')),
  fetchRequiredApi: vi.fn(),
}));
vi.mock('../../../../../api/recognition', async () => ({
  ...(await vi.importActual<typeof import('../../../../../api/recognition')>('../../../../../api/recognition')),
  fetchPendingSuggestions: vi
    .fn()
    .mockResolvedValue({ suggestions: [], limit: 25, offset: 0, data_source: 'local_projection' }),
  fetchPendingMergeSuggestions: vi.fn().mockResolvedValue({ suggestions: [], limit: 10, offset: 0 }),
  fetchPendingNameSuggestions: vi
    .fn()
    .mockResolvedValue({ suggestions: [], limit: 25, offset: 0, data_source: 'local_projection' }),
}));
vi.mock('../../../../../api/rosterApi', () => ({ listRosterEntries: vi.fn().mockResolvedValue([]) }));
vi.mock('../../../../../hooks/useScrollRestoration', () => ({ useScrollRestoration: () => undefined }));
vi.mock('../../../Panels', () => ({ ScanActionPanel: () => null, isClusteringActive: () => false }));
vi.mock('../../../JobTimeline', () => ({ JobTimeline: () => null }));
vi.mock('../../useLiveReviewTarget', () => ({ useLiveReviewTarget: () => ({ status: 'active', error: null }) }));
vi.mock('../../useOpenReviewTargetLifecycle', () => ({
  useOpenReviewTargetLifecycle: () => ({ reviewClusterId: null }),
}));
vi.mock('../../../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: false },
    status: { currentPhase: 'idle', projectionSyncState: 'idle' },
    history: { activeJobIds: [], jobId: null },
    cancelScan: vi.fn(),
    retryScanStream: vi.fn(),
  }),
}));
vi.mock('../../../ClusterPanelContext', () => ({
  useClusterPanel: () => ({ clusterPanel: { mode: 'none', clusterId: null }, dispatchClusterPanel: vi.fn() }),
}));
vi.mock('../../../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({ mediaQueue: { hasIdentities: true } }),
}));
vi.mock('../../../ReviewSurfaceContext', () => ({
  useReviewSurface: () => ({ cardPrimaryPresent: false, setCardPrimaryPresent: vi.fn() }),
}));

const requests: URL[] = [];
let fail = false;
let release: (() => void) | undefined;
let blockedMinimum: string | undefined;
let unknownTotal = false;
const clients: QueryClient[] = [];
const group = {
  id: 'group-a',
  tenant_id: 'tenant-1',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 8,
  photo_count: 2,
  user_confirmed: false,
  representatives: [
    { id: 'face-a', media_id: '12', bbox: null, is_user_selected: false },
    { id: 'face-b', media_id: '13', bbox: null, is_user_selected: false },
  ],
};
beforeEach(() => {
  fail = false;
  release = undefined;
  blockedMinimum = undefined;
  unknownTotal = false;
  requests.length = 0;
  window.AltContextAdmin = {
    nonce: 'test',
    ajaxUrl: '/ajax',
    tenant_id: 'tenant-1',
    endpoints: { recognitionClusters: 'http://localhost/recognition/clusters' },
  };
  resetConfigCache();
  vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
    suggestions: [],
    limit: 25,
    offset: 0,
    data_source: 'local_projection',
  });
  vi.mocked(fetchRequiredApi).mockImplementation(async (input) => {
    const url = new URL(String(input));
    requests.push(url);
    if (!url.pathname.endsWith('/top-unlabeled')) {
      throw new Error(`Unexpected producer ${url}`);
    }
    if (url.searchParams.get('min_photos') === blockedMinimum) {
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    }
    if (fail) {
      throw new Error('Request failed');
    }
    const minimum = Number(url.searchParams.get('min_photos'));
    const offset = Number(url.searchParams.get('offset'));
    return {
      clusters: minimum >= 5 || offset > 0 ? [] : [group],
      limit: 20,
      total: unknownTotal && minimum ? null : minimum >= 5 ? 0 : 21,
      truncated: minimum < 5 && offset === 0,
      data_source: unknownTotal && minimum ? 'backend_proxy' : 'local_projection',
      singleton_count: 0,
      has_clusters: true,
      repair_pending: false,
    };
  });
});
afterEach(() => {
  cleanup();
  clients.forEach((c) => c.clear());
  clients.length = 0;
  vi.clearAllMocks();
});
const mount = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  return {
    client,
    ...render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <MergeSurvivorProvider>
            <ScanTabContent compactEmptySections />
          </MergeSurvivorProvider>
        </QueryClientProvider>
      </MemoryRouter>,
    ),
  };
};
it('mounts the filter on the real compact review surface and requests the same population before paging', async () => {
  mount();
  const control = await screen.findByRole('combobox', { name: 'Minimum photos (optional)' });
  await screen.findByTestId('acx-review-card');
  expect((control as HTMLSelectElement).value).toBe('');
  expect(requests[0].searchParams.has('min_photos')).toBe(false);
  expect(screen.getByText('2 photos')).toBeInTheDocument();
  fireEvent.change(control, { target: { value: '2' } });
  await waitFor(() => expect(requests.some((u) => u.searchParams.get('min_photos') === '2')).toBe(true));
  const next = await screen.findByRole('button', { name: 'Next groups page' });
  fireEvent.click(next);
  await waitFor(() =>
    expect(
      requests.some((u) => u.searchParams.get('offset') === '20' && u.searchParams.get('min_photos') === '2'),
    ).toBe(true),
  );
  fireEvent.change(control, { target: { value: '5' } });
  await screen.findByText('No unlabeled groups match this minimum.');
  expect(requests.at(-1)?.searchParams.get('offset')).toBe(null);
  expect(screen.queryByText('All caught up — no items need review')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Clear minimum photos' }));
  await waitFor(() => expect((control as HTMLSelectElement).value).toBe(''));
});
it('keeps the control focused and distinguishes loading, failure, stale data and filtered empty', async () => {
  mount();
  const control = await screen.findByRole('combobox', { name: 'Minimum photos (optional)' });
  await screen.findByTestId('acx-review-card');
  control.focus();
  fail = true;
  fireEvent.change(control, { target: { value: '3' } });
  await screen.findByText('Unable to load unlabeled faces.');
  expect(screen.queryByText('No unlabeled groups match this minimum.')).not.toBeInTheDocument();
  expect(screen.queryByText('All caught up — no items need review')).not.toBeInTheDocument();
  expect(control).toHaveFocus();
  const retry = within(screen.getByTestId('acx-review-queue-top-unlabeled-error')).getByRole('button', {
    name: 'Retry',
  });
  expect(retry).toBeInTheDocument();
  fail = false;
  fireEvent.click(retry);
  await screen.findByTestId('acx-review-card');
});
it('retains a typed name draft while the minimum hides and restores its group', async () => {
  mount();
  const control = await screen.findByRole('combobox', { name: 'Minimum photos (optional)' });
  const name = await screen.findByRole('combobox', { name: 'Name this person' });
  fireEvent.change(name, { target: { value: 'Pending human name' } });
  expect(name).toHaveValue('Pending human name');
  fireEvent.change(control, { target: { value: '5' } });
  await screen.findByText('No unlabeled groups match this minimum.');
  fireEvent.click(screen.getByRole('button', { name: 'Clear minimum photos' }));
  expect(await screen.findByRole('combobox', { name: 'Name this person' })).toHaveValue('Pending human name');
});

it('announces a pending filter without old rows and cancels it on a new minimum', async () => {
  mount();
  const control = await screen.findByRole('combobox', { name: 'Minimum photos (optional)' });
  await screen.findByTestId('acx-review-card');
  blockedMinimum = '3';
  fireEvent.change(control, { target: { value: '3' } });
  await screen.findByText('Loading unlabeled groups…');
  expect(screen.queryByText('All caught up — no items need review')).not.toBeInTheDocument();
  expect(screen.queryByTestId('acx-review-card')).not.toBeInTheDocument();
  const call = vi.mocked(fetchRequiredApi).mock.calls.find(([url]) => String(url).includes('min_photos=3'));
  expect(call?.[1]?.signal).toBeInstanceOf(AbortSignal);
  fireEvent.change(control, { target: { value: '5' } });
  await screen.findByText('No unlabeled groups match this minimum.');
  expect(call?.[1]?.signal?.aborted).toBe(true);
  release?.();
});
it('uses remote continuation with an unknown total and labels cached rows stale after refresh failure', async () => {
  unknownTotal = true;
  const { client } = mount();
  const control = await screen.findByRole('combobox', { name: 'Minimum photos (optional)' });
  await screen.findByTestId('acx-review-card');
  fireEvent.change(control, { target: { value: '2' } });
  await screen.findByText('Total groups unavailable.');
  expect(screen.getByRole('button', { name: 'Next groups page' })).toBeEnabled();
  fail = true;
  await client.invalidateQueries({ predicate: (query) => JSON.stringify(query.queryKey).includes('min_photos') });
  await screen.findByText('Showing previously loaded groups. Refresh failed.');
  expect(screen.getByTestId('acx-review-card')).toBeInTheDocument();
  expect(screen.queryByText('No unlabeled groups match this minimum.')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Next groups page' })).toBeDisabled();
});

it('keeps pending suggestion selection and human naming while filtering only the group producer', async () => {
  vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
    suggestions: [
      {
        id: 'pending-name',
        cluster_id: 'suggested-group',
        suggested_name: 'Existing proposal',
        confidence_score: 0.8,
        source: 'test',
        created_at: '2026-10-31',
        expires_at: null,
      },
    ],
    limit: 25,
    offset: 0,
    data_source: 'local_projection',
  });
  mount();
  const judgment = await screen.findByRole('textbox', { name: 'Independent name judgment' });
  fireEvent.change(judgment, { target: { value: 'My own judgment' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record judgment' }));
  const select = screen.getByTestId('acx-review-select');
  fireEvent.click(select);
  expect(select).toHaveAttribute('aria-pressed', 'true');
  const minimum = screen.getByRole('combobox', { name: 'Minimum photos (optional)' });
  fireEvent.change(minimum, { target: { value: '5' } });
  await screen.findByText('No unlabeled groups match this minimum.');
  expect(screen.getByTestId('acx-review-select')).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByText('My own judgment')).toBeInTheDocument();
  expect(screen.getByTestId('acx-review-card')).toHaveAttribute('data-review-kind', 'name');
});

it('does not resurrect a reviewed group when a filtered page omits it', async () => {
  const { client } = mount();
  const control = await screen.findByRole('combobox', { name: 'Minimum photos (optional)' });
  await screen.findByTestId('acx-review-card');
  dropClusterFromReviewCaches(client, 'group-a', { mode: REVIEW_DROP_MODE.LABEL });
  await waitFor(() => expect(screen.queryByTestId('acx-review-card')).not.toBeInTheDocument());
  fireEvent.change(control, { target: { value: '5' } });
  await screen.findByText('No unlabeled groups match this minimum.');
  fireEvent.click(screen.getByRole('button', { name: 'Clear minimum photos' }));
  await waitFor(() => expect((control as HTMLSelectElement).value).toBe(''));
  await client.invalidateQueries({ predicate: (query) => JSON.stringify(query.queryKey).includes('top-unlabeled') });
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(screen.queryByTestId('acx-review-card')).not.toBeInTheDocument();
});
