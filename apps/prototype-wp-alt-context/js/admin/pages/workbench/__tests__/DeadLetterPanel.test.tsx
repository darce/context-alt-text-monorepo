import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HTTPError } from '../../../utils/http';
import type {
  BulkRetryResponse,
  OutboxListResponse,
  OutboxMutationResponse,
  OutboxOperation,
} from '../../../api/recognition';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
import { useBulkRetryOperations } from '../../../hooks/useBulkRetryOperations';
import { useDeadLetterOperations } from '../../../hooks/useDeadLetterOperations';
import { useDiscardOperation } from '../../../hooks/useDiscardOperation';
import { useOutboxOperations } from '../../../hooks/useOutboxOperations';
import { useRetryOperation } from '../../../hooks/useRetryOperation';
import { useSyncStatus } from '../../../hooks/useSyncStatus';
import { DeadLetterPanel } from '../DeadLetterPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]): string => {
    let result = text;
    for (const value of values) {
      result = result.replace(/%(?:[0-9]+\$)?[sd]/, String(value));
    }
    return result;
  },
}));

vi.mock('../../../hooks/useBulkRetryOperations', () => ({
  useBulkRetryOperations: vi.fn(),
}));

vi.mock('../../../hooks/useDeadLetterOperations', () => ({
  useDeadLetterOperations: vi.fn(),
}));

vi.mock('../../../hooks/useRetryOperation', () => ({
  useRetryOperation: vi.fn(),
}));

vi.mock('../../../hooks/useOutboxOperations', () => ({
  useOutboxOperations: vi.fn(),
}));

vi.mock('../../../hooks/useDiscardOperation', () => ({
  useDiscardOperation: vi.fn(),
}));

vi.mock('../../../hooks/useSyncStatus', () => ({
  useSyncStatus: vi.fn(),
}));

type DeadLetterRow = OutboxOperation & {
  first_failed_at?: string | null;
  age_seconds?: number | null;
};

type DeadLetterList = OutboxListResponse & {
  now?: string | null;
  oldest_age_seconds?: number | null;
  items: DeadLetterRow[];
};

type WpDateBootstrap = {
  date?: {
    getSettings?: () => { timezone?: { offset?: number } };
  };
};

const buildOperation = (overrides: Partial<DeadLetterRow> = {}): DeadLetterRow => ({
  id: 11,
  tenant_id: 'tenant-1',
  operation_type: 'cluster_label_updated',
  entity_type: 'cluster',
  entity_key: 'cluster-1',
  status: 'failed',
  attempts: 5,
  expected_base_version: 11,
  local_revision: 4,
  last_error_code: 'dispatch_failed',
  last_error_message: 'Remote curation replay failed.',
  created_at: '2026-03-11T10:00:00Z',
  last_attempted_at: '2026-03-11T10:05:00Z',
  acknowledged_at: null,
  payload: { label: 'Renamed' },
  ...overrides,
});

const listResponse = (overrides: Partial<DeadLetterList> = {}): DeadLetterList => ({
  items: [buildOperation()],
  total: 1,
  limit: 20,
  offset: 0,
  ...overrides,
});

describe('DeadLetterPanel', () => {
  const mockedUseBulkRetryOperations = vi.mocked(useBulkRetryOperations);
  const mockedUseDeadLetterOperations = vi.mocked(useDeadLetterOperations);
  const mockedUseRetryOperation = vi.mocked(useRetryOperation);
  const mockedUseOutboxOperations = vi.mocked(useOutboxOperations);
  const mockedUseDiscardOperation = vi.mocked(useDiscardOperation);
  const mockedUseSyncStatus = vi.mocked(useSyncStatus);

  const renderPanel = () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    return render(
      <QueryClientProvider client={client}>
        <DeadLetterPanel />
      </QueryClientProvider>,
    );
  };

  const mockFailedPages = (
    primary: DeadLetterList,
    eligibility: { data?: DeadLetterList; status?: 'pending' | 'error'; error?: Error } = {},
  ) => {
    mockedUseDeadLetterOperations.mockImplementation((params) => {
      if (params?.limit === 50) {
        if (eligibility.status === 'pending') {
          return createMockQuery<OutboxListResponse>({ status: 'pending' });
        }
        if (eligibility.status === 'error') {
          return createMockQuery<OutboxListResponse>({
            status: 'error',
            isError: true,
            error: eligibility.error ?? new Error('Boom'),
          });
        }
        return createMockQuery<OutboxListResponse>({
          data: eligibility.data ?? primary,
        });
      }

      return createMockQuery<OutboxListResponse>({ data: primary });
    });
  };

  const setSiteGmtOffsetHours = (offset: number): void => {
    (window as Window & { wp?: WpDateBootstrap }).wp = {
      date: {
        getSettings: () => ({ timezone: { offset } }),
      },
    };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    delete (window as Window & { wp?: WpDateBootstrap }).wp;
    mockedUseBulkRetryOperations.mockReturnValue(
      createMockMutation<BulkRetryResponse, Error, void>({
        mutateAsync: vi.fn().mockResolvedValue({ requeued: 1, failed_remaining: 0 }),
      }),
    );
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [buildOperation()],
          total: 1,
          limit: 20,
          offset: 0,
        },
      }),
    );
    mockedUseRetryOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync: vi.fn().mockResolvedValue({ operation: null }),
      }),
    );
    mockedUseOutboxOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              id: 31,
              status: 'acknowledged',
              acknowledged_at: '2026-03-11T10:07:00Z',
              last_attempted_at: '2026-03-11T10:06:00Z',
            }),
          ],
          total: 1,
          limit: 10,
          offset: 0,
        },
      }),
    );
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync: vi.fn().mockResolvedValue({ operation: null }),
      }),
    );
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 4,
          last_synced_at: '2026-03-11T10:00:00Z',
          is_stale: false,
          sync_health: 'healthy',
          last_sync_result: 'ok',
          topology_commands: {
            pending: 0,
            applied: 0,
            failed: 0,
            conflict: 0,
            last_reconciled_at: null,
          },
        },
      }),
    );
  });

  it('keeps visible loading copy alongside the screen-reader status', () => {
    mockedUseDeadLetterOperations.mockReturnValue(createMockQuery<OutboxListResponse>({ status: 'pending' }));

    renderPanel();

    const visibleLoading = screen
      .getAllByText('Loading failed changes…')
      .find((node) => !node.classList.contains('screen-reader-text'));
    expect(visibleLoading).toBeVisible();
  });

  it('mounts the empty failed-changes status before announcing loading on the same node', () => {
    vi.useFakeTimers();
    try {
      mockedUseDeadLetterOperations.mockReturnValue(createMockQuery<OutboxListResponse>({ status: 'pending' }));

      renderPanel();

      const status = screen.getByTestId('acx-dead-letter-status');
      expect(status).toBeEmptyDOMElement();
      expect(screen.getByRole('region', { name: 'Failed changes panel' })).toHaveAttribute('aria-busy', 'true');

      act(() => {
        vi.runOnlyPendingTimers();
      });

      expect(screen.getByTestId('acx-dead-letter-status')).toBe(status);
      expect(status).toHaveTextContent('Loading failed changes…');
    } finally {
      vi.useRealTimers();
    }
  });

  it('renders error state', () => {
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        status: 'error',
        isError: true,
        error: new Error('Boom'),
      }),
    );

    renderPanel();

    expect(screen.getByText('Unable to load failed changes.')).toBeInTheDocument();
  });

  it('announces load failures assertively with a non-colour warning icon', () => {
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        status: 'error',
        isError: true,
        error: new Error('Boom'),
      }),
    );

    renderPanel();

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Unable to load failed changes.');
    expect(alert.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('always renders an initially empty polite mutation status region', () => {
    renderPanel();

    const status = screen.getByTestId('acx-dead-letter-status');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toBeEmptyDOMElement();
  });

  it('renders empty state', () => {
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: { items: [], total: 0, limit: 20, offset: 0 },
      }),
    );

    renderPanel();

    expect(screen.getByText('No failed changes to retry.')).toBeInTheDocument();
    expect(screen.getByText('Showing 0-0 of 0 failed changes.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh failed changes' })).toBeEnabled();
  });

  it('renders failed operations with metadata and payload summary', () => {
    renderPanel();

    expect(screen.getByText('Failed changes')).toBeInTheDocument();
    expect(screen.getByText('Showing 1-1 of 1 failed changes.')).toBeInTheDocument();
    expect(screen.getAllByText('Cluster label update')).toHaveLength(2);
    expect(screen.getAllByText('Entity: cluster-1 (cluster)')).toHaveLength(2);
    expect(screen.getByText('Attempts: 5')).toBeInTheDocument();
    expect(screen.getAllByText(/Last attempted:/)).toHaveLength(2);
    expect(screen.getByText('Error: dispatch_failed: Remote curation replay failed.')).toBeInTheDocument();
    expect(screen.getByText('Payload label: Renamed')).toBeInTheDocument();
  });

  it('renders outbox timeline entries with status and acknowledgement metadata', () => {
    renderPanel();

    expect(screen.getByText('Pending changes timeline')).toBeInTheDocument();
    expect(screen.getByText('Showing 1-1 of 1 changes (all statuses).')).toBeInTheDocument();
    expect(screen.getByText('Status: acknowledged')).toBeInTheDocument();
    expect(screen.getByText(/Acknowledged:/)).toBeInTheDocument();
  });

  it('updates the timeline filter and pagination controls', () => {
    mockedUseOutboxOperations.mockImplementation((params) =>
      createMockQuery<OutboxListResponse>({
        data: {
          items:
            params?.offset === 10
              ? [
                  buildOperation({
                    id: 42,
                    status: 'pending',
                    entity_key: 'cluster-42',
                    last_attempted_at: null,
                    acknowledged_at: null,
                  }),
                ]
              : [
                  buildOperation({
                    id: 41,
                    status: params?.status ?? 'acknowledged',
                    acknowledged_at: '2026-03-11T10:07:00Z',
                  }),
                ],
          total: 11,
          limit: 10,
          offset: params?.offset ?? 0,
        },
      }),
    );

    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: 'pending' }));
    expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({
      limit: 10,
      offset: 0,
      status: 'pending',
    });

    fireEvent.click(screen.getByRole('button', { name: 'Next timeline page' }));
    expect(screen.getByText('Entity: cluster-42 (cluster)')).toBeInTheDocument();
  });

  it('surfaces topology command status via pending-work vocabulary (no Sync backlog)', () => {
    mockedUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 4,
          last_synced_at: '2026-03-11T10:00:00Z',
          is_stale: false,
          sync_health: 'queued',
          last_sync_result: 'ok',
          topology_commands: {
            pending: 2,
            applied: 1,
            failed: 1,
            conflict: 3,
            last_reconciled_at: null,
          },
        },
      }),
    );

    renderPanel();

    expect(screen.getByText('2 waiting, 1 synced, 1 failed, 3 need review')).toBeInTheDocument();
    expect(screen.queryByText(/Sync backlog/i)).not.toBeInTheDocument();
  });

  it('renders pagination state and advances to the next page', () => {
    mockedUseDeadLetterOperations.mockImplementation((params) =>
      createMockQuery<OutboxListResponse>({
        data: {
          items:
            params?.offset === 20
              ? [
                  buildOperation({
                    id: 21,
                    entity_key: 'cluster-21',
                    payload: { label: 'Second page' },
                  }),
                ]
              : [buildOperation()],
          total: 21,
          limit: 20,
          offset: params?.offset ?? 0,
        },
      }),
    );

    renderPanel();

    expect(screen.getByText('Showing 1-1 of 21 failed changes.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    expect(screen.getByText('Showing 21-21 of 21 failed changes.')).toBeInTheDocument();
    expect(screen.getByText('Entity: cluster-21 (cluster)')).toBeInTheDocument();
  });

  it('retries an operation and shows success notice', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ operation: null });
    mockedUseRetryOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync,
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(11);
    });

    expect(screen.getByRole('status')).toHaveTextContent(
      'Cluster label update for cluster-1 (operation 11) queued to retry.',
    );
  });

  it('shows mutation error feedback when retry fails', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('boom'));
    mockedUseRetryOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync,
      }),
    );
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [buildOperation(), buildOperation({ id: 12, entity_key: 'cluster-2' })],
          total: 2,
          limit: 20,
          offset: 0,
        },
      }),
    );

    renderPanel();
    const selectedRow = screen.getByText('Entity: cluster-2 (cluster)').closest('li');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow!).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(12);
    });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(
      'Unable to retry Cluster label update for cluster-2 (operation 12). Please try again.',
    );
    expect(alert.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('requires confirmation before discard and shows success notice', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ operation: null });
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync,
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));

    expect(screen.getByRole('button', { name: 'Confirm discard' })).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm discard' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(11);
    });

    expect(screen.getByRole('status')).toHaveTextContent(
      'Cluster label update for cluster-1 (operation 11) discarded.',
    );
  });

  it('shows mutation error feedback when discard fails', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('boom'));
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync,
      }),
    );
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [buildOperation(), buildOperation({ id: 12, entity_key: 'cluster-2' })],
          total: 2,
          limit: 20,
          offset: 0,
        },
      }),
    );

    renderPanel();
    const selectedRow = screen.getByText('Entity: cluster-2 (cluster)').closest('li');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow!).getByRole('button', { name: 'Discard' }));
    fireEvent.click(within(selectedRow!).getByRole('button', { name: 'Confirm discard' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(12);
    });

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Unable to discard Cluster label update for cluster-2 (operation 12). Please try again.',
    );
  });

  it('announces retry pending and success with the selected row identity', async () => {
    let resolveRetry!: (value: OutboxMutationResponse) => void;
    const mutateAsync = vi.fn(
      () =>
        new Promise<OutboxMutationResponse>((resolve) => {
          resolveRetry = resolve;
        }),
    );
    mockedUseRetryOperation.mockReturnValue(createMockMutation<OutboxMutationResponse, Error, number>({ mutateAsync }));
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [buildOperation(), buildOperation({ id: 12, entity_key: 'cluster-2' })],
          total: 2,
          limit: 20,
          offset: 0,
        },
      }),
    );

    renderPanel();
    const selectedRow = screen.getByText('Entity: cluster-2 (cluster)').closest('li');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow!).getByRole('button', { name: 'Retry' }));

    expect(screen.getByRole('status')).toHaveTextContent('Retrying Cluster label update for cluster-2 (operation 12).');

    await act(async () => {
      resolveRetry({ operation: null });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(
        'Cluster label update for cluster-2 (operation 12) queued to retry.',
      );
    });
  });

  it('announces discard confirmation, pending, and success with the selected row identity', async () => {
    let resolveDiscard!: (value: OutboxMutationResponse) => void;
    const mutateAsync = vi.fn(
      () =>
        new Promise<OutboxMutationResponse>((resolve) => {
          resolveDiscard = resolve;
        }),
    );
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({ mutateAsync }),
    );
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [buildOperation(), buildOperation({ id: 12, entity_key: 'cluster-2' })],
          total: 2,
          limit: 20,
          offset: 0,
        },
      }),
    );

    renderPanel();
    const selectedRow = screen.getByText('Entity: cluster-2 (cluster)').closest('li');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow!).getByRole('button', { name: 'Discard' }));
    expect(screen.getByRole('status')).toHaveTextContent(
      'Discard armed for Cluster label update for cluster-2 (operation 12). Activate Confirm discard to continue.',
    );

    fireEvent.click(within(selectedRow!).getByRole('button', { name: 'Confirm discard' }));
    expect(screen.getByRole('status')).toHaveTextContent(
      'Discarding Cluster label update for cluster-2 (operation 12).',
    );

    await act(async () => {
      resolveDiscard({ operation: null });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(
        'Cluster label update for cluster-2 (operation 12) discarded.',
      );
    });
  });

  it('shows the bulk retry control with the failed count', () => {
    renderPanel();

    const button = screen.getByRole('button', { name: 'Retry all failed (1)' });
    expect(button).toBeEnabled();
  });

  it('disables the bulk retry control at zero failed changes while keeping the count visible', () => {
    // rg-003 intent: the bulk action is inherently N-dependent, so zero-state renders
    // the control disabled with the (0) count visible rather than hiding it.
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: { items: [], total: 0, limit: 20, offset: 0 },
      }),
    );

    renderPanel();

    expect(screen.getByRole('button', { name: 'Retry all failed (0)' })).toBeDisabled();
  });

  it('requires confirmation before bulk retry and shows the requeued count on success', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ requeued: 5, failed_remaining: 0 });
    mockedUseBulkRetryOperations.mockReturnValue(
      createMockMutation<BulkRetryResponse, Error, void>({
        mutateAsync,
      }),
    );
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: { items: [buildOperation()], total: 5, limit: 20, offset: 0 },
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Retry all failed (5)' }));

    expect(screen.getByRole('button', { name: 'Confirm retry all failed (5)' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Retry all is armed. Activate Confirm retry all failed to queue 5 failed changes.',
    );
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm retry all failed (5)' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByText('5 failed changes queued to retry.')).toBeInTheDocument();
    // failed_remaining: 0 -> no remainder copy.
    expect(screen.queryByText(/remain — run again to queue the rest/)).not.toBeInTheDocument();
  });

  it('surfaces the remainder when the bulk retry response reports failed changes left over', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ requeued: 1000, failed_remaining: 234 });
    mockedUseBulkRetryOperations.mockReturnValue(
      createMockMutation<BulkRetryResponse, Error, void>({
        mutateAsync,
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Retry all failed (1)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm retry all failed (1)' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledTimes(1);
    });

    expect(
      screen.getByText('1000 failed changes queued to retry. 234 remain — run again to queue the rest.'),
    ).toBeInTheDocument();
  });

  it('auto-disarms the bulk retry confirmation after the timeout', () => {
    vi.useFakeTimers();
    try {
      const mutateAsync = vi.fn().mockResolvedValue({ requeued: 1, failed_remaining: 0 });
      mockedUseBulkRetryOperations.mockReturnValue(
        createMockMutation<BulkRetryResponse, Error, void>({
          mutateAsync,
        }),
      );

      renderPanel();
      fireEvent.click(screen.getByRole('button', { name: 'Retry all failed (1)' }));
      expect(screen.getByRole('button', { name: 'Confirm retry all failed (1)' })).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(9000);
      });

      // Disarmed: the next click re-arms instead of firing the mutation.
      const button = screen.getByRole('button', { name: 'Retry all failed (1)' });
      fireEvent.click(button);
      expect(mutateAsync).not.toHaveBeenCalled();
      expect(screen.getByRole('button', { name: 'Confirm retry all failed (1)' })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('disarms the bulk retry confirmation when the failed total changes', () => {
    const mutateAsync = vi.fn().mockResolvedValue({ requeued: 1, failed_remaining: 0 });
    mockedUseBulkRetryOperations.mockReturnValue(
      createMockMutation<BulkRetryResponse, Error, void>({
        mutateAsync,
      }),
    );

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <DeadLetterPanel />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Retry all failed (1)' }));
    expect(screen.getByRole('button', { name: 'Confirm retry all failed (1)' })).toBeInTheDocument();

    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [buildOperation(), buildOperation({ id: 12, entity_key: 'cluster-2' })],
          total: 2,
          limit: 20,
          offset: 0,
        },
      }),
    );
    rerender(
      <QueryClientProvider client={client}>
        <DeadLetterPanel />
      </QueryClientProvider>,
    );

    // Disarmed by the total change: the next click re-arms instead of firing.
    const button = screen.getByRole('button', { name: 'Retry all failed (2)' });
    fireEvent.click(button);
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Confirm retry all failed (2)' })).toBeInTheDocument();
  });

  it('shows progress while the bulk retry is pending', () => {
    mockedUseBulkRetryOperations.mockReturnValue(
      createMockMutation<BulkRetryResponse, Error, void>({
        isPending: true,
        mutateAsync: vi.fn(),
      }),
    );

    renderPanel();

    const button = screen.getByRole('button', { name: 'Retrying all failed…' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    const reasonId = button.getAttribute('aria-describedby');
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId!)).toHaveTextContent('Failed-change action in progress. Please wait.');
    expect(document.getElementById(reasonId!)).not.toHaveClass('screen-reader-text');
    expect(screen.getByRole('region', { name: 'Failed changes panel' })).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Retrying all failed changes…');
  });

  it('shows mutation error feedback when bulk retry fails', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('boom'));
    mockedUseBulkRetryOperations.mockReturnValue(
      createMockMutation<BulkRetryResponse, Error, void>({
        mutateAsync,
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Retry all failed (1)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm retry all failed (1)' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByRole('alert')).toHaveTextContent('Unable to retry all failed changes. Please try again.');
  });

  it('describes row actions disabled by another pending queue mutation', () => {
    mockedUseRetryOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({ isPending: true, mutateAsync: vi.fn() }),
    );

    renderPanel();

    for (const button of [
      screen.getByRole('button', { name: 'Retry' }),
      screen.getByRole('button', { name: 'Discard' }),
    ]) {
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute('aria-disabled', 'true');
      const reasonId = button.getAttribute('aria-describedby');
      expect(reasonId).toBeTruthy();
      expect(document.getElementById(reasonId!)).toHaveTextContent('Failed-change action in progress. Please wait.');
    }
  });

  it('shows age per failed row and timeline entry', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-19T10:00:00Z'));
    try {
      renderPanel();

      expect(screen.getAllByText('Age: 8 days')).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows Will not retry for terminal failed rows and hides Retry', () => {
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              last_error_code: 'unauthorized',
              last_error_message: 'Session expired.',
            }),
          ],
          total: 1,
          limit: 20,
          offset: 0,
        },
      }),
    );

    renderPanel();

    expect(screen.getByText('Will not retry')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument();
  });

  it('shows Will not retry for discarded timeline rows', () => {
    mockedUseOutboxOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              id: 44,
              status: 'discarded',
              last_error_code: 'auto_retry_exhausted',
            }),
          ],
          total: 1,
          limit: 10,
          offset: 0,
        },
      }),
    );

    renderPanel();

    expect(screen.getByText('Will not retry')).toBeInTheDocument();
  });

  it('keeps Discard 0 eligible visible and disabled at zero failed changes', () => {
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: { items: [], total: 0, limit: 20, offset: 0 },
      }),
    );

    renderPanel();

    expect(screen.getByRole('button', { name: 'Discard 0 eligible' })).toBeDisabled();
  });

  it('requests a bulk-discard page of at most 50 failed changes', () => {
    renderPanel();

    expect(mockedUseDeadLetterOperations).toHaveBeenCalledWith({ limit: 50, offset: 0 });
  });

  it('requires confirmation before discarding failed changes older than 7 days', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ operation: null });
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({ mutateAsync }),
    );
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              id: 11,
              first_failed_at: '2026-09-01T00:00:00Z',
              last_attempted_at: '2026-09-01T00:00:00Z',
              created_at: '2026-09-01T00:00:00Z',
              age_seconds: 16 * 24 * 3600,
            }),
            buildOperation({
              id: 12,
              entity_key: 'cluster-2',
              first_failed_at: '2026-09-16T00:00:00Z',
              last_attempted_at: '2026-09-16T00:00:00Z',
              created_at: '2026-09-16T00:00:00Z',
              age_seconds: 1 * 24 * 3600,
            }),
          ],
          total: 2,
          limit: 50,
          offset: 0,
        },
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Discard 1 eligible' }));

    expect(screen.getByRole('button', { name: 'Confirm discard 1 eligible' })).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Discard 1 eligible is armed. Activate Confirm discard 1 eligible to continue.',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Confirm discard 1 eligible' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledTimes(1);
    });
    expect(mutateAsync).toHaveBeenCalledWith(11);

    expect(screen.getByTestId('acx-bulk-discard-results')).toHaveTextContent(
      'Cluster label update for cluster-1 (operation 11) discarded.',
    );
    expect(
      screen.getByText('Discarded 1 failed changes older than 7 days. 1 remain — run again for the next page.'),
    ).toBeInTheDocument();
  });

  it('stops the bulk discard on the first auth or 4xx and shows per-row results', async () => {
    const mutateAsync = vi
      .fn()
      .mockResolvedValueOnce({ operation: null })
      .mockRejectedValueOnce(
        new HTTPError({
          status: 403,
          retryAfterSeconds: undefined,
          endpoint: '/acx/v1/recognition/outbox/12/discard',
          bodyPreview: '',
          message: 'forbidden',
        }),
      )
      .mockResolvedValue({ operation: null });
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({ mutateAsync }),
    );
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              id: 11,
              first_failed_at: '2026-09-01T00:00:00Z',
              last_attempted_at: '2026-09-01T00:00:00Z',
              created_at: '2026-09-01T00:00:00Z',
              age_seconds: 16 * 24 * 3600,
            }),
            buildOperation({
              id: 12,
              entity_key: 'cluster-2',
              first_failed_at: '2026-09-01T00:00:00Z',
              last_attempted_at: '2026-09-01T00:00:00Z',
              created_at: '2026-09-01T00:00:00Z',
              age_seconds: 16 * 24 * 3600,
            }),
            buildOperation({
              id: 13,
              entity_key: 'cluster-3',
              first_failed_at: '2026-09-01T00:00:00Z',
              last_attempted_at: '2026-09-01T00:00:00Z',
              created_at: '2026-09-01T00:00:00Z',
              age_seconds: 16 * 24 * 3600,
            }),
          ],
          total: 3,
          limit: 50,
          offset: 0,
        },
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Discard 3 eligible' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm discard 3 eligible' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledTimes(2);
    });
    expect(mutateAsync).not.toHaveBeenCalledWith(13);

    const results = screen.getByTestId('acx-bulk-discard-results');
    expect(results).toHaveTextContent('Cluster label update for cluster-1 (operation 11) discarded.');
    expect(results).toHaveTextContent(
      'Stopped before discarding Cluster label update for cluster-2 (operation 12) (authorization or client error).',
    );
    expect(
      screen.getByText(
        'Stopped after an authorization or client error. 1 discarded. 2 remain — run again for the next page.',
      ),
    ).toBeInTheDocument();
  });

  it('treats an old first failure with a recent retry as eligible via age_seconds', () => {
    mockFailedPages(
      listResponse({
        items: [
          buildOperation({
            id: 11,
            first_failed_at: '2026-09-01T00:00:00Z',
            last_attempted_at: '2026-09-16T00:00:00Z',
            created_at: '2026-08-01T00:00:00Z',
            age_seconds: 16 * 24 * 3600,
          }),
          buildOperation({
            id: 12,
            entity_key: 'cluster-2',
            first_failed_at: '2026-09-16T00:00:00Z',
            last_attempted_at: '2026-09-16T00:00:00Z',
            created_at: '2026-08-01T00:00:00Z',
            age_seconds: 1 * 24 * 3600,
          }),
        ],
        total: 2,
        limit: 50,
      }),
    );

    renderPanel();

    expect(screen.getByRole('button', { name: 'Discard 1 eligible' })).toBeEnabled();
  });

  it('derives eligibility from age_seconds when the failure-age stamps are missing', () => {
    mockFailedPages(
      listResponse({
        items: [
          buildOperation({
            id: 11,
            created_at: null,
            last_attempted_at: null,
            first_failed_at: null,
            age_seconds: 8 * 24 * 3600,
          }),
          buildOperation({
            id: 12,
            entity_key: 'cluster-2',
            created_at: null,
            last_attempted_at: null,
            first_failed_at: null,
            age_seconds: 2 * 24 * 3600,
          }),
        ],
        total: 2,
        limit: 50,
      }),
    );

    renderPanel();

    expect(screen.getByRole('button', { name: 'Discard 1 eligible' })).toBeEnabled();
  });

  it('disables bulk discard while the 50-row eligibility query is loading', () => {
    mockFailedPages(
      listResponse({
        items: [buildOperation({ created_at: '2026-09-01T00:00:00Z' })],
        total: 1,
      }),
      { status: 'pending' },
    );

    renderPanel();

    expect(screen.getByRole('button', { name: 'Discard 0 eligible' })).toBeDisabled();
  });

  it('disables bulk discard when the 50-row eligibility query errors and does not fall back to the 20-row page', () => {
    mockFailedPages(
      listResponse({
        items: [buildOperation({ created_at: '2026-09-01T00:00:00Z' })],
        total: 1,
      }),
      { status: 'error', error: new Error('Boom') },
    );

    renderPanel();

    expect(screen.getByRole('button', { name: 'Discard 0 eligible' })).toBeDisabled();
    expect(screen.getByText('Showing 1-1 of 1 failed changes.')).toBeInTheDocument();
  });

  it('enables bulk discard from the 50-row eligibility page even when the 20-row page has no eligible rows', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-17T12:00:00Z'));
    try {
      mockFailedPages(
        listResponse({
          items: [
            buildOperation({
              id: 21,
              first_failed_at: '2026-09-16T00:00:00Z',
              last_attempted_at: '2026-09-16T00:00:00Z',
              created_at: '2026-09-16T00:00:00Z',
              age_seconds: 1 * 24 * 3600,
            }),
          ],
          total: 2,
          limit: 20,
        }),
        {
          data: listResponse({
            items: [
              buildOperation({
                id: 21,
                first_failed_at: '2026-09-16T00:00:00Z',
                last_attempted_at: '2026-09-16T00:00:00Z',
                created_at: '2026-09-16T00:00:00Z',
                age_seconds: 1 * 24 * 3600,
              }),
              buildOperation({
                id: 11,
                entity_key: 'cluster-old',
                first_failed_at: '2026-09-01T00:00:00Z',
                last_attempted_at: '2026-09-01T00:00:00Z',
                created_at: '2026-09-01T00:00:00Z',
                age_seconds: 16 * 24 * 3600,
              }),
            ],
            total: 2,
            limit: 50,
          }),
        },
      );

      renderPanel();

      expect(screen.getByRole('button', { name: 'Discard 1 eligible' })).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not shift the 7-day boundary when the browser zone differs from the site zone', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-17T08:00:00Z'));
    const getTimezoneOffset = vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(480);
    setSiteGmtOffsetHours(9);
    try {
      mockFailedPages(
        listResponse({
          items: [
            buildOperation({
              first_failed_at: '2026-09-10 12:00:00',
              last_attempted_at: '2026-09-10 12:00:00',
              created_at: '2026-09-10 12:00:00',
            }),
          ],
          total: 1,
          limit: 50,
          now: '2026-09-17T08:00:00Z',
        }),
      );

      renderPanel();

      expect(screen.getByRole('button', { name: 'Discard 1 eligible' })).toBeEnabled();
    } finally {
      getTimezoneOffset.mockRestore();
      vi.useRealTimers();
    }
  });

  it('compares site-local timestamps against a server-anchored now when the list carries one', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-16T12:00:00Z'));
    setSiteGmtOffsetHours(0);
    try {
      mockFailedPages(
        listResponse({
          items: [
            buildOperation({
              first_failed_at: '2026-09-10 12:00:00',
              last_attempted_at: '2026-09-10 12:00:00',
              created_at: '2026-09-10 12:00:00',
            }),
          ],
          total: 1,
          limit: 50,
          now: '2026-09-17 12:00:00',
        }),
      );

      renderPanel();

      expect(screen.getByRole('button', { name: 'Discard 1 eligible' })).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('never treats a row without age_seconds, first_failed_at, and now as eligible', () => {
    mockFailedPages(
      listResponse({
        items: [
          buildOperation({
            created_at: '2026-08-01T00:00:00Z',
            last_attempted_at: '2026-08-01T00:00:00Z',
            first_failed_at: null,
            age_seconds: null,
          }),
        ],
        total: 1,
        limit: 50,
      }),
    );

    renderPanel();

    const button = screen.getByRole('button', { name: 'Discard 0 eligible' });
    expect(button).toBeDisabled();
    expect(screen.getByText('Failure age unavailable from server')).toBeInTheDocument();
    expect(button).toHaveAttribute('aria-describedby', 'acx-dead-letter-age-unavailable-reason');
  });
});
