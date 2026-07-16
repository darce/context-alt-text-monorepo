import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { BulkRetryResponse, OutboxListResponse, OutboxMutationResponse, OutboxOperation } from '../../../api/recognition';
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

const buildOperation = (overrides: Partial<OutboxOperation> = {}): OutboxOperation => ({
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

  beforeEach(() => {
    vi.clearAllMocks();
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

  it('renders loading state', () => {
    mockedUseDeadLetterOperations.mockReturnValue(createMockQuery<OutboxListResponse>({ status: 'pending' }));

    renderPanel();

    expect(screen.getByText('Loading failed changes…')).toBeInTheDocument();
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

  it('renders empty state', () => {
    mockedUseDeadLetterOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: { items: [], total: 0, limit: 20, offset: 0 },
      }),
    );

    renderPanel();

    expect(screen.getByText('No failed changes.')).toBeInTheDocument();
    expect(screen.getByText('Showing 0-0 of 0 failed changes.')).toBeInTheDocument();
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

  it('surfaces topology command status when backlog exists', () => {
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

    expect(screen.getByText('Sync backlog: 2 waiting, 1 applied, 1 failed, 3 conflicts.')).toBeInTheDocument();
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

    expect(screen.getByText('Change queued to retry.')).toBeInTheDocument();
  });

  it('shows mutation error feedback when retry fails', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('boom'));
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

    expect(screen.getByText('Unable to retry this operation. Please try again.')).toBeInTheDocument();
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

    expect(screen.getByText('Failed change discarded.')).toBeInTheDocument();
  });

  it('shows mutation error feedback when discard fails', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('boom'));
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync,
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm discard' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(11);
    });

    expect(screen.getByText('Unable to discard this operation. Please try again.')).toBeInTheDocument();
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
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm retry all failed (5)' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByText('5 failed changes queued to retry.')).toBeInTheDocument();
  });

  it('shows progress while the bulk retry is pending', () => {
    mockedUseBulkRetryOperations.mockReturnValue(
      createMockMutation<BulkRetryResponse, Error, void>({
        isPending: true,
        mutateAsync: vi.fn(),
      }),
    );

    renderPanel();

    expect(screen.getByRole('button', { name: 'Retrying all failed…' })).toBeDisabled();
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

    expect(screen.getByText('Unable to retry all failed changes. Please try again.')).toBeInTheDocument();
  });
});
