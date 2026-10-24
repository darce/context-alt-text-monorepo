// @vitest-environment jsdom
/**
 * FIR402-GATE-01 portable regression: the merge gate's caller reproduction
 * (gate-review/fir402-caller-concern.test.ts), re-homed with repo-relative paths.
 * Actual source mutationFns, scanFacesBatched and caller callbacks run; only the
 * HTTP/config/toast/offline boundaries are replaced and useMutation returns its
 * options so callbacks are driven explicitly. The gate's two observation tests
 * asserted the defect (success-only result, no refusal); they are ported as the
 * acceptance they observed missing.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HTTPError } from '../../../utils/errorTaxonomy';
import { scanFacesBatched } from '../scanApi';
import type { BatchAnalyzeResponse } from '../types';
import { useScanIdentities } from '../../../hooks/useRecognitionHooks';
import { useClusterActions } from '../../../pages/roster/hooks/useClusterActions';

const state = vi.hoisted(() => ({
  fetch: vi.fn<(endpoint: string, options?: { body?: unknown }) => Promise<unknown>>(),
  success: vi.fn(),
  error: vi.fn(),
}));
vi.mock('../../config', () => ({
  getEndpoint: (name: string) => (name === 'recognitionAnalyze' ? '/analyze' : '/batch-runs'),
  getConfig: () => ({ nonce: 'review-only', maxMediaPerBatch: 5 }),
  isDevMode: () => false,
}));
vi.mock('../../../utils/http', () => ({
  fetchRequiredApi: (endpoint: string, options?: { body?: unknown }) => state.fetch(endpoint, options),
}));
vi.mock('../index', async () => ({
  scanFacesBatched: (await import('../scanApi')).scanFacesBatched,
}));
vi.mock('@tanstack/react-query', () => ({
  useMutation: (options: unknown) => options,
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: unknown[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));
vi.mock('../../../context/ToastContext', () => ({
  useToast: () => ({ success: state.success, error: state.error }),
}));
vi.mock('../../../hooks/useSyncOffline', () => ({ useSyncOffline: () => false }));

/** useMutation is mocked to return its options; this is the slice the test drives. */
interface CapturedMutation<TVariables> {
  mutationFn: (variables: TVariables) => Promise<BatchAnalyzeResponse>;
  onSuccess: (data: BatchAnalyzeResponse) => void;
  onError: (error: Error) => void;
}
interface RescanVariables {
  cluster: { id: string; sample_identities: { media_id: number }[] };
  mediaIds: number[];
}
const captured = <TVariables>(options: unknown): CapturedMutation<TVariables> =>
  options as CapturedMutation<TVariables>;

const ALLOWANCE_COPY =
  'The account usage allowance is unavailable or insufficient for this scan. Check Usage & billing.';
const ids = Array.from({ length: 15 }, (_, i) => i + 1);
const accepted = {
  id: 'accepted-first-five',
  type: 'analyze',
  status: 'pending',
  progress: { completed: 0, total: 5 },
  started_at: '',
  finished_at: null,
};
const refusal = new HTTPError({
  status: 402,
  endpoint: '/analyze',
  bodyPreview: '{"detail":{"reason":"insufficient_credits"}}',
  retryAfterSeconds: undefined,
  message: 'Allowance exhausted',
});
const prepareLaterRefusal = () =>
  state.fetch.mockResolvedValueOnce(accepted).mockRejectedValueOnce(refusal).mockResolvedValue({ status: 'recorded' });
const analyzeCalls = () => state.fetch.mock.calls.filter(([url]) => url === '/analyze');

beforeEach(() => {
  vi.clearAllMocks();
  state.fetch.mockReset();
});

describe('FIR402 late global refusal: actual caller mutationFns', () => {
  it('ordinary mutationFn keeps the accepted jobs and carries the original later refusal', async () => {
    prepareLaterRefusal();
    const options = captured<number[]>(useScanIdentities());
    const result = await options.mutationFn(ids);
    expect(result.jobs).toEqual([accepted]);
    expect(result.refusal).toBe(refusal);
    expect(analyzeCalls()).toHaveLength(2);
    expect(state.fetch.mock.calls[2]?.[1]?.body).toEqual({
      batch_index: 1,
      submitted_total: 15,
      media_ids: ids.slice(5),
    });
  });

  it('roster onSuccess reports the accepted start and surfaces the refusal', async () => {
    prepareLaterRefusal();
    const options = captured<RescanVariables>(useClusterActions().rescanMutation);
    const result = await options.mutationFn({ cluster: { id: 'cluster-1', sample_identities: [] }, mediaIds: ids });
    options.onSuccess(result);
    expect(state.success).toHaveBeenCalledWith('Started sensitive rescan (job accepted-first-five).');
    expect(state.error).toHaveBeenCalledWith(ALLOWANCE_COPY);
  });

  it('initial global refusal preserves the exact original exception', async () => {
    state.fetch.mockRejectedValueOnce(refusal).mockResolvedValue({ status: 'recorded' });
    await expect(scanFacesBatched({ mediaIds: ids })).rejects.toBe(refusal);
  });
});

it('BLOCKING ACCEPTANCE: roster surfaces a global admission refusal after earlier accepted work', async () => {
  prepareLaterRefusal();
  const options = captured<RescanVariables>(useClusterActions().rescanMutation);
  const variables = { cluster: { id: 'cluster-1', sample_identities: [] }, mediaIds: ids };
  let result: BatchAnalyzeResponse | undefined;
  try {
    result = await options.mutationFn(variables);
  } catch (error) {
    options.onError(error as Error);
  }
  if (result) {
    // Follow the actual mutation success callback while retaining accepted work.
    expect(result.jobs).toContainEqual(accepted);
    options.onSuccess(result);
  }
  // A global denial requires visible recovery even when earlier jobs were accepted.
  expect(state.error, 'The original global refusal must reach the caller recovery path').toHaveBeenCalled();
});
