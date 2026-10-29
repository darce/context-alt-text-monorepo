import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

const catalog = vi.hoisted(() => {
  const labels: Record<string, string> = {};
  return {
    labels,
    polish: false,
    plural: vi.fn<(singular: string, plural: string, count: number, domain: string) => void>(),
  };
});
vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => catalog.labels[text] ?? text,
  _n: (singular: string, plural: string, count: number, domain: string) => {
    catalog.plural(singular, plural, count, domain);
    if (catalog.polish) {
      return `${count === 1 ? 'one' : count % 10 >= 2 && count % 10 <= 4 && !(count % 100 >= 12 && count % 100 <= 14) ? 'few' : 'many'} %1$s-%2$s/%3$s (%4$s)`;
    }
    return count === 1 ? singular : plural;
  },
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

interface WpDateBootstrap {
  date?: {
    getSettings?: () => { timezone?: { offset?: number } };
  };
}

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

  const getTimelinePanel = (): HTMLElement => {
    const heading = screen.getByRole('heading', { name: 'Change history' });
    const panel = heading.parentElement;
    expect(panel).not.toBeNull();
    return panel!;
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
    catalog.labels = {};
    catalog.polish = false;
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


  describe('human change identity and waiting time', () => {
    afterEach(() => vi.restoreAllMocks());
    const uuid = 'b274c6a1-5f0e-4c1d-9a7e-123456789abc';

    it.each([
      [{ label: 'Jane Doe' }, 'Cluster label update: “Jane Doe”'],
      [{ label: null }, 'Cluster label cleared'],
      [undefined, 'Cluster label update: b274c6a1'],
      [{ person_id: 'person-42' }, 'Cluster label update: Payload person: person-42'],
    ])('names the change from payload %j', (payload, identity) => {
      mockFailedPages(listResponse({ items: [buildOperation({ entity_key: uuid, payload: payload as OutboxOperation['payload'] })] }));
      renderPanel();
      const heading = screen.getByText(identity, { selector: 'strong' });
      expect(heading).not.toHaveTextContent(uuid);
      const row = heading.closest('li')!;
      expect(within(row).getByText('cluster ' + uuid + ' · change #11')).toBeInTheDocument();
      expect(within(row).getByRole('button', { name: 'Retry ' + identity })).toBeInTheDocument();
      fireEvent.click(within(row).getByRole('button', { name: 'Discard ' + identity }));
      expect(within(row).getByRole('button', { name: 'Confirm discard ' + identity })).toBeInTheDocument();
    });

    it.each([
      [1, 'minute'], [2, 'minutes'], [60, 'hour'], [120, 'hours'],
      [1440, 'day'], [2880, 'days'],
    ])('pluralizes the waiting duration at %i minutes', (minutes, unit) => {
      vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-27T12:00:00Z'));
      const count = minutes < 60 ? minutes : minutes < 1440 ? minutes / 60 : minutes / 1440;
      mockFailedPages(listResponse({ items: [buildOperation({
        created_at: new Date(Date.now() - minutes * 60000).toISOString(),
      })] }));
      renderPanel();
      expect(screen.getByText('Unresolved for ' + count + ' ' + unit)).toBeInTheDocument();
      expect(catalog.plural).toHaveBeenCalledWith(
        expect.stringContaining('%1$d'), expect.stringContaining('%1$d'), count, 'alt-context',
      );
    });

    it.each([29, 30, 31])('marks a change stale after the threshold: %i days', (days) => {
      vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-27T12:00:00Z'));
      mockFailedPages(listResponse({ items: [buildOperation({
        created_at: new Date(Date.now() - days * 86400000).toISOString(),
        last_attempted_at: new Date(Date.now()).toISOString(),
      })] }));
      renderPanel();
      expect(screen.getByText('Unresolved for ' + days + ' days')).toBeInTheDocument();
      if (days > 30) {
        expect(screen.getByText(/Stale: From/)).toHaveTextContent('over 31 days ago');
      } else {
        expect(screen.queryByText(/Stale: From/)).not.toBeInTheDocument();
      }
    });

    it('shows how long a pending change has waited', () => {
      vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-27T12:00:00Z'));
      mockedUseOutboxOperations.mockReturnValue(createMockQuery<OutboxListResponse>({
        data: listResponse({ items: [buildOperation({
          status: 'pending', created_at: '2026-10-27T11:00:00Z',
        })] }),
      }));
      renderPanel();
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      expect(screen.getByText('Waiting 1 hour')).toBeInTheDocument();
    });

    it('announces retry using the label identity', async () => {
      mockFailedPages(listResponse({ items: [buildOperation({ payload: { label: 'Jane Doe' } })] }));
      renderPanel();
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Retry Cluster label update: “Jane Doe”' }));
        await Promise.resolve();
      });
      expect(screen.getByRole('status')).toHaveTextContent('Cluster label update: “Jane Doe” queued to retry.');
    });
  });

  describe('UXREC-1 needs attention', () => {
    const OLD_FAILED = buildOperation({
      id: 701,
      entity_key: 'cluster-701',
      created_at: '2026-07-14T09:00:00Z',
      first_failed_at: '2026-07-14T09:00:00Z',
    });
    const PENDING_OP = buildOperation({ id: 702, status: 'pending', last_error_code: null, last_error_message: null });
    const CONFLICT_OP = buildOperation({ id: 703, status: 'conflict' });
    const ACKNOWLEDGED_OP = buildOperation({
      id: 704,
      status: 'acknowledged',
      acknowledged_at: '2026-07-15T09:00:00Z',
    });
    const DISCARDED_OP = buildOperation({ id: 705, status: 'discarded', last_error_code: 'auto_retry_exhausted' });

    beforeEach(() => {
      mockFailedPages(listResponse({ items: [OLD_FAILED] }));
      mockedUseOutboxOperations.mockImplementation((params) => {
        const items = [OLD_FAILED, PENDING_OP, CONFLICT_OP, ACKNOWLEDGED_OP, DISCARDED_OP].filter(
          (op) => !params?.status || op.status === params.status,
        );
        return createMockQuery<OutboxListResponse>({
          data: { items, total: 25, limit: 10, offset: params?.offset ?? 0 },
        });
      });
    });

    // Predicted RED: missing accessible Needs attention button on unchanged consumer.
    it('defaults to Needs attention › Failed with the failed list only', () => {
      renderPanel();
      expect(screen.getByRole('button', { name: 'Needs attention' })).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', { name: 'Failed' })).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getAllByText('cluster cluster-701 · change #701')).toHaveLength(1);
      expect(mockedUseOutboxOperations).not.toHaveBeenCalled();
      expect(screen.queryByRole('heading', { name: 'Change history' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Retry all failed (1)' })).toBeInTheDocument();
    });

    it('Pending and Conflict render only the server-filtered timeline', () => {
      renderPanel();
      for (const [label, status, heading] of [
        ['Pending', 'pending', 'Pending changes'],
        ['Conflict', 'conflict', 'Conflicted changes'],
      ]) {
        fireEvent.click(screen.getByRole('button', { name: label }));
        expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status });
        expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
        expect(screen.queryByTestId('acx-zone-z-dl-actions')).not.toBeInTheDocument();
        expect(screen.queryByText('Showing 1-1 of 1 failed changes.')).not.toBeInTheDocument();
      }
    });

    it('History renders the all-status timeline with guarded failed-row recovery and no bulk controls', async () => {
      renderPanel();
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status: undefined });
      expect(screen.getByText('Status: acknowledged')).toBeInTheDocument();
      expect(screen.getByText('Status: discarded')).toBeInTheDocument();
      expect(screen.queryByTestId('acx-zone-z-dl-actions')).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'failed' }));
      expect(screen.getAllByText('cluster cluster-701 · change #701')).toHaveLength(1);
      fireEvent.click(screen.getByRole('button', { name: /^Retry Cluster/ }));
      await waitFor(() => expect(mockedUseRetryOperation().mutateAsync).toHaveBeenCalledWith(701));
      fireEvent.click(screen.getByRole('button', { name: /^Discard Cluster/ }));
      expect(mockedUseDiscardOperation().mutateAsync).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: /^Confirm discard Cluster/ }));
      await waitFor(() => expect(mockedUseDiscardOperation().mutateAsync).toHaveBeenCalledWith(701));
    });

    it('view changes reset the timeline offset and disarm confirmations', () => {
      renderPanel();
      fireEvent.click(screen.getByRole('button', { name: /^Discard Cluster/ }));
      expect(screen.getByRole('button', { name: /^Confirm discard Cluster/ })).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      fireEvent.click(screen.getByRole('button', { name: 'Next timeline page' }));
      expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 10, status: undefined });
      fireEvent.click(screen.getByRole('button', { name: 'Needs attention' }));
      expect(screen.getByRole('button', { name: /^Discard Cluster/ })).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Retry all failed (1)' }));
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      fireEvent.click(screen.getByRole('button', { name: 'Needs attention' }));
      expect(screen.getByRole('button', { name: 'Retry all failed (1)' })).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Pending' }));
      expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status: 'pending' });
    });

    it('failed-list load error keeps History reachable', () => {
      mockedUseDeadLetterOperations.mockReturnValue(
        createMockQuery<OutboxListResponse>({ status: 'error', error: new Error('Boom') }),
      );
      renderPanel();
      expect(screen.getByText('Unable to load failed changes.')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      expect(screen.getByRole('heading', { name: 'Change history' })).toBeInTheDocument();
    });

    it('old failed rows stay in Needs attention until the server status changes', () => {
      renderPanel();
      expect(screen.getAllByText('cluster cluster-701 · change #701')).toHaveLength(1);
      expect(screen.getByRole('button', { name: 'Retry all failed (1)' })).toBeInTheDocument();
    });

    it('view changes never send a mutation', () => {
      renderPanel();
      for (const name of ['Pending', 'Conflict', 'History', 'Needs attention', 'Failed']) {
        fireEvent.click(screen.getByRole('button', { name }));
      }
      expect(mockedUseRetryOperation().mutateAsync).not.toHaveBeenCalled();
      expect(mockedUseDiscardOperation().mutateAsync).not.toHaveBeenCalled();
      expect(mockedUseBulkRetryOperations().mutateAsync).not.toHaveBeenCalled();
    });

    it('History filters expose pressed state and stay focusable', () => {
      renderPanel();
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      const all = screen.getByRole('button', { name: 'All' });
      expect(all).toHaveAttribute('aria-pressed', 'true');
      expect(all).toBeEnabled();
      const failed = screen.getByRole('button', { name: 'failed' });
      fireEvent.click(failed);
      expect(failed).toHaveAttribute('aria-pressed', 'true');
      expect(all).toHaveAttribute('aria-pressed', 'false');
      fireEvent.click(screen.getByRole('button', { name: 'Next timeline page' }));
      fireEvent.click(failed);
      expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 10, status: 'failed' });
    });

    it('History labels and moved count use literal gettext and explicit host locale', () => {
      const previous = document.documentElement.lang;
      document.documentElement.lang = 'ar-EG';
      try {
        mockedUseOutboxOperations.mockReturnValue(
          createMockQuery<OutboxListResponse>({
            data: { items: [ACKNOWLEDGED_OP, DISCARDED_OP], total: 1234, limit: 10, offset: 0 },
          }),
        );
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'History' }));
        const fmt = new Intl.NumberFormat('ar-EG', { maximumFractionDigits: 0 });
        expect(fmt.format(2)).not.toBe('2');
        expect(
          screen.getByText(`Showing ${fmt.format(1)}-${fmt.format(2)} of ${fmt.format(1234)} changes (all statuses).`),
        ).toBeInTheDocument();
        expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status: undefined });
      } finally {
        document.documentElement.lang = previous;
      }
    });

    // UXREC-1 TIMELINE_GATE-01: an actual view, filter or page transition disarms every
    // confirmation and its confirmation-only announcement; Discard must be armed again.
    describe('UXREC-1 navigation disarms confirmations', () => {
      const OLD_FAILED_ARMED =
        'Discard armed for Cluster label update: “Renamed”. Activate Confirm discard to continue.';
      const oldFailedRow = (): HTMLElement => {
        const row = screen.getByText('cluster cluster-701 · change #701').closest('li');
        expect(row).not.toBeNull();
        return row!;
      };
      const expectRearmRequired = async (): Promise<void> => {
        const discard = mockedUseDiscardOperation().mutateAsync;
        expect(within(oldFailedRow()).queryByRole('button', { name: /^Confirm discard Cluster/ })).not.toBeInTheDocument();
        expect(screen.getByTestId('acx-dead-letter-status')).not.toHaveTextContent('Discard armed');
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Discard Cluster/ }));
        expect(discard).not.toHaveBeenCalled();
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Confirm discard Cluster/ }));
        await waitFor(() => expect(discard).toHaveBeenCalledWith(701));
      };

      it('History All to failed disarms the row that stays visible', async () => {
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'History' }));
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Discard Cluster/ }));
        expect(screen.getByTestId('acx-dead-letter-status')).toHaveTextContent(OLD_FAILED_ARMED);
        fireEvent.click(screen.getByRole('button', { name: 'failed' }));
        expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status: 'failed' });
        await expectRearmRequired();
      });

      it('History page-away and back disarms the row', async () => {
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'History' }));
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Discard Cluster/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Next timeline page' }));
        expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 10, status: undefined });
        expect(within(oldFailedRow()).queryByRole('button', { name: /^Confirm discard Cluster/ })).not.toBeInTheDocument();
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Discard Cluster/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Previous timeline page' }));
        expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status: undefined });
        await expectRearmRequired();
      });

      it('cached same-total failed pages disarm row and bulk confirmations', async () => {
        mockFailedPages(listResponse({ items: [{ ...OLD_FAILED, age_seconds: 16 * 24 * 3600 }], total: 25 }));
        renderPanel();
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Discard Cluster/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Next' }));
        expect(mockedUseDeadLetterOperations).toHaveBeenLastCalledWith({ limit: 50, offset: 0 });
        expect(mockedUseDeadLetterOperations).toHaveBeenCalledWith({ limit: 20, offset: 20 });
        fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
        expect(mockedUseDeadLetterOperations).toHaveBeenCalledWith({ limit: 20, offset: 0 });
        await expectRearmRequired();

        fireEvent.click(screen.getByRole('button', { name: 'Retry all failed (25)' }));
        fireEvent.click(screen.getByRole('button', { name: 'Next' }));
        expect(screen.getByRole('button', { name: 'Retry all failed (25)' })).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Discard eligible failed changes' }));
        fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
        expect(screen.getByRole('button', { name: 'Discard eligible failed changes' })).toBeInTheDocument();
        expect(screen.getByTestId('acx-dead-letter-status')).not.toHaveTextContent(/armed/);
        expect(mockedUseBulkRetryOperations().mutateAsync).not.toHaveBeenCalled();
        expect(mockedUseDiscardOperation().mutateAsync).toHaveBeenCalledTimes(1);
      });

      it('view changes clear the stale row discard announcement', async () => {
        renderPanel();
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Discard Cluster/ }));
        expect(screen.getByTestId('acx-dead-letter-status')).toHaveTextContent(OLD_FAILED_ARMED);
        fireEvent.click(screen.getByRole('button', { name: 'History' }));
        expect(screen.getByTestId('acx-dead-letter-status')).not.toHaveTextContent('Discard armed');
        fireEvent.click(screen.getByRole('button', { name: 'Needs attention' }));
        await expectRearmRequired();
      });

      it('same-selection no-ops keep the confirmation armed', () => {
        renderPanel();
        fireEvent.click(screen.getByRole('button', { name: 'History' }));
        fireEvent.click(screen.getByRole('button', { name: 'failed' }));
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Discard Cluster/ }));
        fireEvent.click(screen.getByRole('button', { name: 'failed' }));
        fireEvent.click(screen.getByRole('button', { name: 'History' }));
        expect(within(oldFailedRow()).getByRole('button', { name: /^Confirm discard Cluster/ })).toBeInTheDocument();
        expect(screen.getByTestId('acx-dead-letter-status')).toHaveTextContent(OLD_FAILED_ARMED);
        expect(mockedUseDiscardOperation().mutateAsync).not.toHaveBeenCalled();
      });

      it('navigation keeps in-flight retry feedback', () => {
        mockedUseRetryOperation.mockReturnValue(
          createMockMutation<OutboxMutationResponse, Error, number>({
            mutateAsync: vi.fn(() => new Promise<OutboxMutationResponse>(() => undefined)),
          }),
        );
        renderPanel();
        fireEvent.click(within(oldFailedRow()).getByRole('button', { name: /^Retry Cluster/ }));
        const inFlight = 'Retrying Cluster label update: “Renamed”.';
        expect(screen.getByTestId('acx-dead-letter-status')).toHaveTextContent(inFlight);
        fireEvent.click(screen.getByRole('button', { name: 'History' }));
        fireEvent.click(screen.getByRole('button', { name: 'Next timeline page' }));
        fireEvent.click(screen.getByRole('button', { name: 'failed' }));
        expect(screen.getByTestId('acx-dead-letter-status')).toHaveTextContent(inFlight);
        expect(mockedUseRetryOperation().mutateAsync).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe('UXREC-1 timeline locale boundary', () => {
    let hostLang: string | null;
    beforeEach(() => {
      hostLang = document.documentElement.getAttribute('lang');
      document.documentElement.lang = 'en-US';
      vi.spyOn(navigator, 'language', 'get').mockReturnValue('ar-EG');
    });
    afterEach(() => {
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
      if (hostLang === null) {
        document.documentElement.removeAttribute('lang');
      } else {
        document.documentElement.lang = hostLang;
      }
      catalog.labels = {};
      catalog.polish = false;
    });
    const historyWithTotal = (total: number) => {
      mockedUseOutboxOperations.mockReturnValue(
        createMockQuery<OutboxListResponse>({
          data: {
            items:
              total === 0
                ? []
                : [
                    buildOperation({ status: 'acknowledged' }),
                    ...(total > 1 ? [buildOperation({ id: 12, status: 'discarded' })] : []),
                  ],
            total,
            limit: 10,
            offset: 0,
          },
        }),
      );
      renderPanel();
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      return screen.getByTestId('acx-dead-letter-timeline-status');
    };
    it.each([0, 1, 2, 1234])('uses explicit English display and raw total %i', (total) => {
      expect(Intl.NumberFormat.supportedLocalesOf(['en-US'])).toContain('en-US');
      const format = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
      const line = historyWithTotal(total);
      expect(line).toHaveTextContent(
        `Showing ${total === 0 ? '0' : '1'}-${Math.min(total, 2)} of ${format.format(total)} ${total === 1 ? 'change' : 'changes'} (all statuses).`,
      );
      expect(catalog.plural).toHaveBeenCalledWith(
        'Showing %1$s-%2$s of %3$s change (%4$s).',
        'Showing %1$s-%2$s of %3$s changes (%4$s).',
        total,
        'alt-context',
      );
    });
    it.each([1, 2, 22, 1234])('uses explicit Arabic display for %i without changing server params', (total) => {
      document.documentElement.lang = 'ar-EG';
      expect(Intl.NumberFormat.supportedLocalesOf(['ar-EG'])).toContain('ar-EG');
      const format = new Intl.NumberFormat('ar-EG', { maximumFractionDigits: 0 });
      expect(format.format(2)).not.toBe('2');
      expect(historyWithTotal(total)).toHaveTextContent(
        `Showing ${format.format(1)}-${format.format(Math.min(total, 2))} of ${format.format(total)} ${total === 1 ? 'change' : 'changes'} (all statuses).`,
      );
      expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status: undefined });
    });
    it.each([null, '', '   ', 'en_US', 'not_a_locale'])(
      'uses neutral raw display for missing or malformed host %s',
      (lang) => {
        if (lang === null) {
          document.documentElement.removeAttribute('lang');
        } else {
          document.documentElement.lang = lang;
        }
        const constructor = vi.spyOn(Intl, 'NumberFormat');
        expect(historyWithTotal(1234)).toHaveTextContent('Showing 1-2 of 1234 changes (all statuses).');
        expect(constructor).not.toHaveBeenCalled();
      },
    );
    it('uses neutral raw display for explicitly unsupported host locale', () => {
      document.documentElement.lang = 'ar-EG';
      vi.spyOn(Intl.NumberFormat, 'supportedLocalesOf').mockReturnValue([]);
      const constructor = vi.spyOn(Intl, 'NumberFormat');
      expect(historyWithTotal(1234)).toHaveTextContent('Showing 1-2 of 1234 changes (all statuses).');
      expect(constructor).not.toHaveBeenCalled();
    });
    it('uses neutral raw display when locale support lookup fails', () => {
      vi.spyOn(Intl.NumberFormat, 'supportedLocalesOf').mockImplementation(() => {
        throw new Error('Intl unavailable');
      });
      const constructor = vi.spyOn(Intl, 'NumberFormat');
      expect(historyWithTotal(1234)).toHaveTextContent('Showing 1-2 of 1234 changes (all statuses).');
      expect(constructor).not.toHaveBeenCalled();
    });
    it('uses neutral raw display with missing Intl APIs', () => {
      vi.stubGlobal('Intl', {});
      expect(historyWithTotal(1234)).toHaveTextContent('Showing 1-2 of 1234 changes (all statuses).');
    });
    it('uses neutral raw display when formatting fails', () => {
      const descriptor = Object.getOwnPropertyDescriptor(Intl.NumberFormat.prototype, 'format');
      if (!descriptor) {
        throw new Error('Expected NumberFormat format accessor');
      }
      Object.defineProperty(Intl.NumberFormat.prototype, 'format', {
        configurable: true,
        get: () => () => {
          throw new Error('format failed');
        },
      });
      try {
        expect(historyWithTotal(1234)).toHaveTextContent('Showing 1-2 of 1234 changes (all statuses).');
      } finally {
        Object.defineProperty(Intl.NumberFormat.prototype, 'format', descriptor);
      }
    });
    it('uses neutral raw display when formatter construction fails', () => {
      vi.spyOn(Intl, 'NumberFormat').mockImplementation(function () {
        throw new Error('constructor failed');
      });
      expect(historyWithTotal(1234)).toHaveTextContent('Showing 1-2 of 1234 changes (all statuses).');
    });
    it.each(['pending', 'error'] as const)('announces timeline %s on one polite status container', (status) => {
      mockedUseOutboxOperations.mockReturnValue(
        status === 'error'
          ? createMockQuery<OutboxListResponse>({ status: 'error', error: new Error('Boom') })
          : createMockQuery<OutboxListResponse>({ status: 'pending' }),
      );
      renderPanel();
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      const live = screen.getByTestId('acx-dead-letter-timeline-status');
      expect(live).toHaveAttribute('aria-live', 'polite');
      expect(live).toHaveTextContent(status === 'pending' ? 'Loading changes…' : 'Unable to load changes.');
      expect(screen.queryByTestId('acx-zone-z-dl-actions')).not.toBeInTheDocument();
    });
    it('translates literal History labels while query tokens stay raw', () => {
      catalog.labels = {
        All: 'Tous',
        pending: 'en attente',
        acknowledged: 'reçu',
        conflict: 'conflit',
        failed: 'échec',
        discarded: 'écarté',
        'all statuses': 'tous les états',
      };
      expect(historyWithTotal(2)).toHaveTextContent('Showing 1-2 of 2 changes (tous les états).');
      for (const token of ['pending', 'acknowledged', 'conflict', 'failed', 'discarded']) {
        fireEvent.click(screen.getByRole('button', { name: catalog.labels[token] }));
        expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status: token });
        expect(screen.getByTestId('acx-dead-letter-timeline-status')).toHaveTextContent(`(${catalog.labels[token]}).`);
      }
      fireEvent.click(screen.getByRole('button', { name: 'Tous' }));
      expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({ limit: 10, offset: 0, status: undefined });
    });
    it.each([
      [1, 'one'],
      [2, 'few'],
      [5, 'many'],
      [11, 'many'],
      [22, 'few'],
    ] as const)('passes raw %i to a multi-form catalog', (total, form) => {
      catalog.polish = true;
      document.documentElement.lang = 'ar-EG';
      const format = new Intl.NumberFormat('ar-EG', { maximumFractionDigits: 0 });
      expect(historyWithTotal(total)).toHaveTextContent(
        `${form} ${format.format(1)}-${format.format(Math.min(total, 2))}/${format.format(total)} (all statuses)`,
      );
      expect(catalog.plural).toHaveBeenCalledWith(
        'Showing %1$s-%2$s of %3$s change (%4$s).',
        'Showing %1$s-%2$s of %3$s changes (%4$s).',
        total,
        'alt-context',
      );
    });
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
      expect(screen.getByRole('region', { name: 'Changes panel' })).toHaveAttribute('aria-busy', 'true');

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
    expect(screen.getAllByText('Cluster label update: “Renamed”')).toHaveLength(1);
    expect(screen.getAllByText('cluster cluster-1 · change #11')).toHaveLength(1);
    expect(screen.getByText('Attempts: 5')).toBeInTheDocument();
    expect(screen.getAllByText(/Last attempted:/)).toHaveLength(1);
    expect(screen.getByText('Error: dispatch_failed: Remote curation replay failed.')).toBeInTheDocument();
    expect(screen.queryByText('Payload label: Renamed')).not.toBeInTheDocument();
  });

  it('renders outbox timeline entries with status and acknowledgement metadata', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    expect(screen.getByText('Change history')).toBeInTheDocument();
    expect(screen.getByText('Showing 1-1 of 1 change (all statuses).')).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    fireEvent.click(screen.getByRole('button', { name: 'pending' }));
    expect(mockedUseOutboxOperations).toHaveBeenLastCalledWith({
      limit: 10,
      offset: 0,
      status: 'pending',
    });

    fireEvent.click(screen.getByRole('button', { name: 'Next timeline page' }));
    expect(screen.getByText('cluster cluster-42 · change #42')).toBeInTheDocument();
  });

  it('keeps non-failed timeline rows without error, attempts, or recovery actions', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    const timeline = within(getTimelinePanel());
    const row = within(timeline.getByRole('listitem'));
    expect(row.getByText('Cluster label update: “Renamed”', { selector: 'strong' })).toBeInTheDocument();
    expect(row.getByText('Status: acknowledged')).toBeInTheDocument();
    expect(row.queryByText(/Attempts:/)).not.toBeInTheDocument();
    expect(row.queryByText(/^Error:/)).not.toBeInTheDocument();
    expect(row.queryByRole('button', { name: /^Retry(?:\s|$)/ })).not.toBeInTheDocument();
    expect(row.queryByRole('button', { name: /^Discard(?:\s|$)/ })).not.toBeInTheDocument();
  });

  it('shows error code, attempts, and Retry/Discard on failed timeline rows', () => {
    mockedUseOutboxOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              id: 51,
              status: 'failed',
              attempts: 4,
              entity_key: 'cluster-51',
              last_error_code: 'dispatch_failed',
              last_error_message: 'Remote curation replay failed.',
            }),
          ],
          total: 1,
          limit: 10,
          offset: 0,
        },
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    const timeline = within(getTimelinePanel());
    expect(timeline.getByText('Status: failed')).toBeInTheDocument();
    expect(timeline.getByText('Attempts: 4')).toBeInTheDocument();
    expect(timeline.getByText('Error: dispatch_failed: Remote curation replay failed.')).toBeInTheDocument();
    expect(timeline.getByRole('button', { name: /^Retry Cluster/ })).toBeEnabled();
    expect(timeline.getByRole('button', { name: /^Discard Cluster/ })).toBeEnabled();
  });

  it('retries a failed timeline row through the shared retry mutation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ operation: null });
    mockedUseRetryOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync,
      }),
    );
    mockedUseOutboxOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              id: 51,
              status: 'failed',
              entity_key: 'cluster-51',
            }),
          ],
          total: 1,
          limit: 10,
          offset: 0,
        },
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    fireEvent.click(within(getTimelinePanel()).getByRole('button', { name: /^Retry Cluster/ }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(51);
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      'Cluster label update: “Renamed” queued to retry.',
    );
  });

  it('discards a failed timeline row through the shared discard mutation', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ operation: null });
    mockedUseDiscardOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync,
      }),
    );
    mockedUseOutboxOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              id: 51,
              status: 'failed',
              entity_key: 'cluster-51',
            }),
          ],
          total: 1,
          limit: 10,
          offset: 0,
        },
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));
    const timeline = within(getTimelinePanel());
    fireEvent.click(timeline.getByRole('button', { name: /^Discard Cluster/ }));
    expect(mutateAsync).not.toHaveBeenCalled();
    fireEvent.click(timeline.getByRole('button', { name: /^Confirm discard Cluster/ }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(51);
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      'Cluster label update: “Renamed” discarded.',
    );
  });

  it('hides Retry on terminal failed timeline rows and keeps Discard', () => {
    mockedUseOutboxOperations.mockReturnValue(
      createMockQuery<OutboxListResponse>({
        data: {
          items: [
            buildOperation({
              id: 52,
              status: 'failed',
              entity_key: 'cluster-52',
              last_error_code: 'unauthorized',
              last_error_message: 'Session expired.',
            }),
          ],
          total: 1,
          limit: 10,
          offset: 0,
        },
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'History' }));

    const timeline = within(getTimelinePanel());
    expect(timeline.getByText('Will not retry')).toBeInTheDocument();
    expect(timeline.getByText('Error: unauthorized: Session expired.')).toBeInTheDocument();
    expect(timeline.queryByRole('button', { name: /^Retry Cluster/ })).not.toBeInTheDocument();
    expect(timeline.getByRole('button', { name: /^Discard Cluster/ })).toBeInTheDocument();
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
    expect(screen.getByText('cluster cluster-21 · change #21')).toBeInTheDocument();
  });

  it('retries an operation and shows success notice', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ operation: null });
    mockedUseRetryOperation.mockReturnValue(
      createMockMutation<OutboxMutationResponse, Error, number>({
        mutateAsync,
      }),
    );

    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /^Retry Cluster/ }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(11);
    });

    expect(screen.getByRole('status')).toHaveTextContent(
      'Cluster label update: “Renamed” queued to retry.',
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
    const selectedRow = screen.getByText('cluster cluster-2 · change #12').closest('li');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow!).getByRole('button', { name: /^Retry Cluster/ }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(12);
    });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(
      'Unable to retry Cluster label update: “Renamed”. Please try again.',
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
    fireEvent.click(screen.getByRole('button', { name: /^Discard Cluster/ }));

    expect(screen.getByRole('button', { name: /^Confirm discard Cluster/ })).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /^Confirm discard Cluster/ }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(11);
    });

    expect(screen.getByRole('status')).toHaveTextContent(
      'Cluster label update: “Renamed” discarded.',
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
    const selectedRow = screen.getByText('cluster cluster-2 · change #12').closest('li');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow!).getByRole('button', { name: /^Discard Cluster/ }));
    fireEvent.click(within(selectedRow!).getByRole('button', { name: /^Confirm discard Cluster/ }));

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(12);
    });

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Unable to discard Cluster label update: “Renamed”. Please try again.',
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
    const selectedRow = screen.getByText('cluster cluster-2 · change #12').closest('li');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow!).getByRole('button', { name: /^Retry Cluster/ }));

    expect(screen.getByRole('status')).toHaveTextContent('Retrying Cluster label update: “Renamed”.');

    await act(async () => {
      resolveRetry({ operation: null });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(
        'Cluster label update: “Renamed” queued to retry.',
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
    const selectedRow = screen.getByText('cluster cluster-2 · change #12').closest('li');
    expect(selectedRow).not.toBeNull();
    fireEvent.click(within(selectedRow!).getByRole('button', { name: /^Discard Cluster/ }));
    expect(screen.getByRole('status')).toHaveTextContent(
      'Discard armed for Cluster label update: “Renamed”. Activate Confirm discard to continue.',
    );

    fireEvent.click(within(selectedRow!).getByRole('button', { name: /^Confirm discard Cluster/ }));
    expect(screen.getByRole('status')).toHaveTextContent(
      'Discarding Cluster label update: “Renamed”.',
    );

    await act(async () => {
      resolveDiscard({ operation: null });
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(
        'Cluster label update: “Renamed” discarded.',
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
    expect(screen.getByRole('region', { name: 'Changes panel' })).toHaveAttribute('aria-busy', 'true');
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
      screen.getByRole('button', { name: /^Retry Cluster/ }),
      screen.getByRole('button', { name: /^Discard Cluster/ }),
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

      expect(screen.getAllByText('Unresolved for 8 days')).toHaveLength(1);
      fireEvent.click(screen.getByRole('button', { name: 'History' }));
      expect(screen.getAllByText('Age: 8 days')).toHaveLength(1);
      expect(screen.queryByText('Unresolved for 8 days')).not.toBeInTheDocument();
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
    expect(screen.queryByRole('button', { name: /^Retry Cluster/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Discard Cluster/ })).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: 'History' }));

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
      'Cluster label update: “Renamed” discarded.',
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
    expect(results).toHaveTextContent('Cluster label update: “Renamed” discarded.');
    expect(results).toHaveTextContent(
      'Stopped before discarding Cluster label update: “Renamed” (authorization or client error).',
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
