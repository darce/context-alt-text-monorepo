import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../api/config';
import * as describeApi from '../../../api/describeApi';
import { _resetActiveDescribeRunForTests } from '../../../hooks/activeDescribeRun';
import { _resetDescribeOperationStoreForTests } from '../../../hooks/describeOperationStore';
import { _resetCooldownForTests } from '../../../utils/recognitionCooldown';
import { MediaSelection } from '../MediaSelection';

const { selection, tableBodySpy } = vi.hoisted(() => {
  const selection: Record<string, boolean> = { '11': true };
  return { selection, tableBodySpy: vi.fn() };
});

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _position, explicitIndex) =>
      String(args[explicitIndex ? Number(explicitIndex) - 1 : index++] ?? ''),
    );
  },
}));

vi.mock('../../../api/describeApi', async (importOriginal) => ({
  ...(await importOriginal<typeof describeApi>()),
  fetchBulkDescribeRun: vi.fn(),
  cancelBulkDescribeRun: vi.fn(),
  submitBulkDescribeRun: vi.fn(),
}));

vi.mock('../../../api/settingsApi', () => ({
  fetchSettings: vi.fn(() => Promise.resolve({ recognition_enabled: false })),
}));
vi.mock('../../../api/gpuApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/gpuApi')>()),
  fetchGpuStatus: vi.fn(() => Promise.resolve({ gpu_state: { state: 'ready' }, snapshot_fresh: true })),
}));
vi.mock('../../../hooks/useSyncOffline', () => ({ useSyncOffline: () => false }));
vi.mock('../MediaSelectionTableBody', () => ({
  MediaSelectionTableBody: (props: unknown) => {
    tableBodySpy(props);
    return null;
  },
}));
vi.mock('../WorkbenchNavContext', () => ({ useWorkbenchNav: () => ({ setAdvancedOpen: vi.fn() }) }));
vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: false, progress: null },
    scanAndWait: vi.fn(),
    cancelScan: vi.fn(),
    history: { activeJobIds: [] },
  }),
}));
vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    selection: { selection, toggleRow: vi.fn(), toggleAll: vi.fn() },
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
        isError: false,
        refetch: vi.fn(),
        detailQuery: { isPending: false, isLoading: false, isFetching: false, isError: false, refetch: vi.fn() },
        identitiesQuery: {
          data: { identities_by_media: {}, data_source: 'local_projection' },
          isLoading: false,
          isError: false,
          isPlaceholderData: false,
          isFetching: false,
          refetch: vi.fn(),
        },
      },
      statusMessage: '',
      isStatusPending: false,
    },
  }),
}));

let client: QueryClient;
const mount = (reviewActive = false, activityStatus?: React.ReactNode) =>
  render(
    <QueryClientProvider client={client}>
      <MediaSelection reviewActive={reviewActive} activityStatus={activityStatus} />
    </QueryClientProvider>,
  );
beforeEach(() => {
  vi.clearAllMocks();
  _resetActiveDescribeRunForTests();
  _resetDescribeOperationStoreForTests();
  _resetCooldownForTests();
  sessionStorage.clear();
  resetConfigCache();
  registerConfig({ nonce: 'test', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: {}, tenant_id: 'geometry' });
  Object.keys(selection).forEach((key) => delete selection[key]);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
});
afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  client.clear();
  _resetActiveDescribeRunForTests();
  _resetDescribeOperationStoreForTests();
  resetConfigCache();
});
describe('MediaSelection persistent selected-media action surface', () => {
  it.each([0, 1, 10])('keeps one guarded Describe for %i selected, before the row scroller', async (count) => {
    for (let id = 1; id <= count; id++) {
      selection[String(id)] = true;
    }
    mount();
    const submit = await screen.findByRole('button', {
      name: count ? `Describe ${count} selected` : 'Describe selected',
    });
    expect(screen.getAllByRole('button', { name: /^Describe/ })).toHaveLength(1);
    if (count === 0) {
      expect(submit).toHaveAttribute('aria-disabled', 'true');
      expect(submit).not.toBeDisabled();
      submit.focus();
      expect(submit).toHaveFocus();
      fireEvent.click(submit);
      expect(describeApi.submitBulkDescribeRun).not.toHaveBeenCalled();
    }
    expect(submit.compareDocumentPosition(screen.getByRole('table')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const actions = screen.getByRole('region', { name: 'Selected media actions' });
    expect(actions).toContainElement(submit);
    expect(actions).toHaveTextContent(`${count} selected`);
    expect(actions.compareDocumentPosition(screen.getByRole('table')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it('separates pagination from selected-media action scope', async () => {
    mount();
    await screen.findByRole('button', { name: 'Describe selected' });
    const actions = screen.getByRole('region', { name: 'Selected media actions' });
    const pagination = screen.getByRole('navigation', { name: 'Media pagination' });
    expect(actions).not.toContainElement(pagination);
    expect(
      pagination.compareDocumentPosition(screen.getByRole('table')) & Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy();
  });
  it('provides a named keyboard-scrollable media boundary', async () => {
    mount();
    await screen.findByRole('button', { name: 'Describe selected' });
    const rows = screen.getByRole('region', { name: 'Media library' });
    expect(rows).toContainElement(screen.getByRole('table'));
    expect(rows).toHaveAttribute('tabindex', '0');
    expect(rows).not.toContainElement(screen.getByRole('button', { name: 'Describe selected' }));
  });
  it('preserves review ownership of the primary accent', async () => {
    selection['11'] = true;
    mount(true);
    const submit = await screen.findByRole('button', { name: 'Describe 1 selected' });
    expect(submit).not.toHaveClass('acx-accent-primary-action');
    expect(describeApi.submitBulkDescribeRun).not.toHaveBeenCalled();
  });
  it('keeps the supplied status and complete disclosures with the guarded selection action', async () => {
    mount(false, <div role="status">Existing run status</div>);
    const submit = await screen.findByRole('button', { name: 'Describe selected' });
    const actions = screen.getByRole('region', { name: 'Selected media actions' });
    expect(within(actions).getAllByText('Existing run status')).toHaveLength(1);
    expect(actions).toContainElement(screen.getByText('0 selected', { exact: true }));
    for (const id of submit.getAttribute('aria-describedby')!.split(' ')) {
      expect(actions).toContainElement(document.getElementById(id));
    }
    expect(within(actions).getByText(/People are not identified/)).toBeVisible();
    expect(within(actions).getByTestId('acx-bulk-describe-gpu-cost')).toBeVisible();
    expect(actions).not.toContainElement(screen.getByRole('searchbox', { name: 'Search media' }));
    expect(actions).not.toContainElement(screen.getByRole('navigation', { name: 'Media pagination' }));
  });
});
