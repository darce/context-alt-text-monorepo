import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../../api/recognition';
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

vi.mock('../../../hooks/useBulkRetryOperations', () => ({ useBulkRetryOperations: vi.fn() }));
vi.mock('../../../hooks/useDeadLetterOperations', () => ({ useDeadLetterOperations: vi.fn() }));
vi.mock('../../../hooks/useDiscardOperation', () => ({ useDiscardOperation: vi.fn() }));
vi.mock('../../../hooks/useOutboxOperations', () => ({ useOutboxOperations: vi.fn() }));
vi.mock('../../../hooks/useRetryOperation', () => ({ useRetryOperation: vi.fn() }));
vi.mock('../../../hooks/useSyncStatus', () => ({ useSyncStatus: vi.fn() }));

const buildOperation = (
  id: number,
  ageSeconds = 8 * 24 * 60 * 60,
): OutboxOperation & { age_seconds: number } => ({
  id,
  tenant_id: 'tenant-1',
  operation_type: 'cluster_label_updated',
  entity_type: 'cluster',
  entity_key: `cluster-${id}`,
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
  age_seconds: ageSeconds,
});

const listResponse = (
  items: (OutboxOperation & { age_seconds: number })[],
  offset: number,
): OutboxListResponse => ({ items, total: 51, limit: 50, offset });

describe('dw2-deadletter-1 bulk discard pagination', () => {
  const mockedUseBulkRetryOperations = vi.mocked(useBulkRetryOperations);
  const mockedUseDeadLetterOperations = vi.mocked(useDeadLetterOperations);
  const mockedUseDiscardOperation = vi.mocked(useDiscardOperation);
  const mockedUseOutboxOperations = vi.mocked(useOutboxOperations);
  const mockedUseRetryOperation = vi.mocked(useRetryOperation);
  const mockedUseSyncStatus = vi.mocked(useSyncStatus);

  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseBulkRetryOperations.mockReturnValue(
      createMockMutation<BulkRetryResponse, Error, void>({
        mutateAsync: vi.fn().mockResolvedValue({ requeued: 0, failed_remaining: 0 }),
      }),
    );
    mockedUseDeadLetterOperations.mockImplementation((params) =>
      createMockQuery<OutboxListResponse>({
        data:
          params?.limit === 50
            ? listResponse(
                Array.from({ length: 50 }, (_, index) => buildOperation(index + 1, 1 * 24 * 60 * 60)),
                0,
              )
            : listResponse([], 0),
      }),
    );
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync: vi.fn().mockResolvedValue({ operation: null }),
      }),
    );
    mockedUseOutboxOperations.mockReturnValue(createMockQuery<OutboxListResponse>({ data: listResponse([], 0) }));
    mockedUseRetryOperation.mockReturnValue(
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

  it('fetches later pages when the first 50 failed rows have no eligible entries', async () => {
    const fetchPage = vi
      .spyOn(recognitionApi, 'fetchFailedOutboxOperations')
      .mockResolvedValue(listResponse([buildOperation(51)], 50));
    const mutateAsync = vi.fn().mockResolvedValue({ operation: null });
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({ mutateAsync }),
    );

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <DeadLetterPanel />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Discard eligible failed changes' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm discard eligible failed changes' }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(51);
    });

    expect(fetchPage).toHaveBeenCalledWith({ limit: 50, offset: 50 });
    expect(mutateAsync).toHaveBeenCalledTimes(1);
  });
});
