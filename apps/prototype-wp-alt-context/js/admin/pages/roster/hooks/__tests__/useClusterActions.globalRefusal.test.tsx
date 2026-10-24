/**
 * FIR402-GATE-01: the roster sensitive-rescan caller, mounted on a real QueryClient
 * with the actual scanFacesBatched. Only HTTP, config, toasts and the offline flag
 * are replaced. A run-wide refusal after accepted chunks must keep the accepted
 * start visible and still surface the refusal.
 */
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthExpiredError, HTTPError } from '../../../../utils/errorTaxonomy';
import { _resetCooldownForTests } from '../../../../utils/recognitionCooldown';
import { useClusterActions } from '../useClusterActions';

const state = vi.hoisted(() => ({ fetch: vi.fn(), success: vi.fn(), error: vi.fn() }));
vi.mock('../../../../api/config', () => ({
  getEndpoint: (name: string) => (name === 'recognitionAnalyze' ? '/analyze' : `/${name}`),
  getConfig: () => ({ nonce: 'test-nonce', maxMediaPerBatch: 5 }),
  isDevMode: () => false,
}));
vi.mock('../../../../utils/http', () => ({
  fetchRequiredApi: (...args: unknown[]): unknown => state.fetch(...args),
}));
vi.mock('../../../../api/recognition', async () => ({
  reassignClusterIdentity: vi.fn(),
  scanFacesBatched: (await import('../../../../api/recognition/scanApi')).scanFacesBatched,
}));
vi.mock('../../../../api/rosterApi', () => ({ commitClusterToRosterEntry: vi.fn() }));
vi.mock('../../../../context/ToastContext', () => ({
  useToast: () => ({ success: state.success, error: state.error }),
}));
vi.mock('../../../../hooks/useSyncOffline', () => ({ useSyncOffline: () => false }));
vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: unknown[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

const PARTIAL_COPY = 'Scanning stopped before all selected images were submitted.';
const ALLOWANCE_COPY =
  'The account usage allowance is unavailable or insufficient for this scan. Check Usage & billing.';
const WAIT_COPY = 'Too many recognition requests. Wait before starting another scan.';

const ids = Array.from({ length: 15 }, (_, i) => i + 1);
const cluster = { id: 'cluster-1', sample_identities: [] };
const job = (id: string) => ({
  id,
  type: 'analyze',
  status: 'pending',
  progress: { completed: 0, total: 5 },
  started_at: '2026-10-24T00:00:00Z',
  finished_at: null,
});
const httpError = (status: number): HTTPError =>
  new HTTPError({
    status,
    endpoint: '/analyze',
    bodyPreview: 'private body',
    retryAfterSeconds: undefined,
    message: `Request to /analyze failed (${status}): private body`,
  });

const RUN_WIDE_REFUSALS: [string, () => Error, string][] = [
  ['HTTP 401', () => httpError(401), PARTIAL_COPY],
  ['HTTP 402', () => httpError(402), ALLOWANCE_COPY],
  ['HTTP 403', () => httpError(403), PARTIAL_COPY],
  ['HTTP 429', () => httpError(429), WAIT_COPY],
  ['session expiry', () => new AuthExpiredError({ endpoint: '/analyze', status: 403 }), PARTIAL_COPY],
];

const analyzeCalls = () => state.fetch.mock.calls.filter(([url]) => url === '/analyze');

const renderActions = () => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useClusterActions(), { wrapper });
};

const rescanAndSettle = async (view: ReturnType<typeof renderActions>): Promise<void> => {
  act(() => {
    view.result.current.rescanMutation.mutate({ cluster, mediaIds: ids });
  });
  await waitFor(() => expect(['success', 'error']).toContain(view.result.current.rescanMutation.status));
};

describe('useClusterActions sensitive rescan: run-wide refusal through the actual scan chain', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.fetch.mockReset();
    _resetCooldownForTests();
  });

  it.each(RUN_WIDE_REFUSALS)(
    'keeps the accepted start and surfaces the %s that stopped later submissions',
    async (_label, makeRefusal, message) => {
      const refusal = makeRefusal();
      state.fetch.mockResolvedValueOnce(job('accepted-first-five')).mockRejectedValueOnce(refusal).mockResolvedValue({
        status: 'recorded',
      });
      const view = renderActions();

      await rescanAndSettle(view);

      expect(view.result.current.rescanMutation.data?.jobs.map(({ id }) => id)).toEqual(['accepted-first-five']);
      expect(state.success).toHaveBeenCalledExactlyOnceWith('Started sensitive rescan (job accepted-first-five).');
      expect(state.error).toHaveBeenCalledExactlyOnceWith(message);
      expect(analyzeCalls()).toHaveLength(2);
    },
  );

  it('still rejects an initial refusal with the identical error through onError', async () => {
    const refusal = httpError(402);
    state.fetch.mockRejectedValueOnce(refusal).mockResolvedValue({ status: 'recorded' });
    const view = renderActions();

    await rescanAndSettle(view);

    expect(view.result.current.rescanMutation.error).toBe(refusal);
    expect(state.error).toHaveBeenCalledExactlyOnceWith(refusal.message);
    expect(state.success).not.toHaveBeenCalled();
    expect(analyzeCalls()).toHaveLength(1);
  });

  it('keeps batch-local partial success without an error toast', async () => {
    state.fetch
      .mockResolvedValueOnce(job('accepted-first-five'))
      .mockRejectedValueOnce(httpError(500))
      .mockResolvedValueOnce({ status: 'recorded' })
      .mockResolvedValueOnce(job('accepted-last-five'));
    const view = renderActions();

    await rescanAndSettle(view);

    expect(state.success).toHaveBeenCalledExactlyOnceWith(
      'Started sensitive rescan (2 batches, first job accepted-first-five).',
    );
    expect(state.error).not.toHaveBeenCalled();
    expect(analyzeCalls()).toHaveLength(3);
  });
});
