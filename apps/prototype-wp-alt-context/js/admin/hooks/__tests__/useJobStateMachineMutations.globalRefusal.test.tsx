/**
 * FIR402-GATE-01: the ordinary scan caller, mounted on a real QueryClient with the
 * actual useScanIdentities -> scanFacesBatched chain. Only HTTP and config are
 * replaced. A run-wide refusal after accepted chunks must keep those jobs tracked
 * for JobPipelineContext and still reach its onScanError recovery path.
 */
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthExpiredError, HTTPError } from '../../utils/errorTaxonomy';
import { _resetCooldownForTests } from '../../utils/recognitionCooldown';
import { useJobStateMachineMutations } from '../useJobStateMachineMutations';

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock('../../api/config', () => ({
  getEndpoint: (name: string) => (name === 'recognitionAnalyze' ? '/analyze' : `/${name}`),
  getConfig: () => ({ nonce: 'test-nonce', maxMediaPerBatch: 5 }),
  isDevMode: () => false,
}));
vi.mock('../../utils/http', () => ({
  fetchRequiredApi: (...args: unknown[]): unknown => fetchMock(...args),
}));
vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: unknown[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

const FALLBACK_COPY = 'Recognition job failed. Please try again.';
const PARTIAL_COPY = 'Scanning stopped before all selected images were submitted.';
const ALLOWANCE_COPY =
  'The account usage allowance is unavailable or insufficient for this scan. Check Usage & billing.';
const WAIT_COPY = 'Too many recognition requests. Wait before starting another scan.';

const ids = Array.from({ length: 15 }, (_, i) => i + 1);
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
const sessionExpired = (): AuthExpiredError => new AuthExpiredError({ endpoint: '/analyze', status: 403 });

/** [label, refusal, message after accepted work, message when nothing was accepted]. */
const RUN_WIDE_REFUSALS: [string, () => Error, string, string][] = [
  ['HTTP 401', () => httpError(401), PARTIAL_COPY, FALLBACK_COPY],
  ['HTTP 402', () => httpError(402), ALLOWANCE_COPY, ALLOWANCE_COPY],
  ['HTTP 403', () => httpError(403), PARTIAL_COPY, FALLBACK_COPY],
  ['HTTP 429', () => httpError(429), WAIT_COPY, WAIT_COPY],
  ['session expiry', sessionExpired, PARTIAL_COPY, FALLBACK_COPY],
];

const analyzeCalls = () => fetchMock.mock.calls.filter(([url]) => url === '/analyze');

const renderMutations = () => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const callbacks = {
    addJob: vi.fn<Parameters<typeof useJobStateMachineMutations>[0]['addJob']>(),
    removeJob: vi.fn(),
    setIsWaitingForScanCompletion: vi.fn(),
    setIsCancellingScan: vi.fn(),
    setActiveBatchRunId: vi.fn(),
    invalidateIdentities: vi.fn(),
    onScanComplete: vi.fn(),
    onScanError: vi.fn(),
  };
  const rendered = renderHook(() => useJobStateMachineMutations({ activeJobIds: [], ...callbacks }), { wrapper });
  return { ...rendered, ...callbacks };
};

const submitAndSettle = async (view: ReturnType<typeof renderMutations>): Promise<void> => {
  act(() => {
    view.result.current.scanMutation.mutate(ids);
  });
  await waitFor(() => expect(['success', 'error']).toContain(view.result.current.scanMutation.status));
};

describe('useJobStateMachineMutations: run-wide refusal through the actual scan chain', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    _resetCooldownForTests();
  });

  it.each(RUN_WIDE_REFUSALS)(
    'tracks the accepted jobs and reports the %s that stopped later submissions',
    async (_label, makeRefusal, partialMessage) => {
      const refusal = makeRefusal();
      fetchMock.mockResolvedValueOnce(job('accepted-first-five')).mockRejectedValueOnce(refusal).mockResolvedValue({
        status: 'recorded',
      });
      const view = renderMutations();

      await submitAndSettle(view);

      const batchRunId: unknown = view.setActiveBatchRunId.mock.calls.at(-1)?.[0];
      expect(batchRunId).toEqual(expect.any(String));
      expect(view.addJob).toHaveBeenCalledExactlyOnceWith('accepted-first-five', 'scan', 5, batchRunId);
      expect(view.setIsWaitingForScanCompletion).toHaveBeenLastCalledWith(true);
      expect(view.onScanComplete).toHaveBeenCalledWith(['accepted-first-five']);
      expect(view.onScanError).toHaveBeenCalledExactlyOnceWith(partialMessage);
      expect(String(view.onScanError.mock.calls[0]?.[0])).not.toContain('private body');
      expect(analyzeCalls()).toHaveLength(2);
    },
  );

  it.each(RUN_WIDE_REFUSALS)(
    'rejects an initial %s with the identical error and tracks no job',
    async (_label, makeRefusal, _partialMessage, initialMessage) => {
      const refusal = makeRefusal();
      fetchMock.mockRejectedValueOnce(refusal).mockResolvedValue({ status: 'recorded' });
      const view = renderMutations();

      await submitAndSettle(view);

      expect(view.result.current.scanMutation.error).toBe(refusal);
      expect(view.onScanError).toHaveBeenCalledExactlyOnceWith(initialMessage);
      expect(view.addJob).not.toHaveBeenCalled();
      expect(analyzeCalls()).toHaveLength(1);
    },
  );

  it('keeps batch-local partial success without a refusal notice', async () => {
    fetchMock
      .mockResolvedValueOnce(job('accepted-first-five'))
      .mockRejectedValueOnce(httpError(500))
      .mockResolvedValueOnce({ status: 'recorded' })
      .mockResolvedValueOnce(job('accepted-last-five'));
    const view = renderMutations();

    await submitAndSettle(view);

    expect(view.result.current.scanMutation.isSuccess).toBe(true);
    expect(view.addJob.mock.calls.map(([id]) => id)).toEqual(['accepted-first-five', 'accepted-last-five']);
    expect(view.onScanError).not.toHaveBeenCalled();
    expect(analyzeCalls()).toHaveLength(3);
  });
});
