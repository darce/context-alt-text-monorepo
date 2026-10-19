import type { QueryClient } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  QUEUE_DRAFT_SOURCE,
  QUEUE_DRAFTS_HISTORY_MAX_PAGES,
  QUEUE_DRAFTS_HISTORY_PAGE_SIZE,
  useQueueDrafts,
} from '../useQueueDrafts';
import * as describeApi from '../../api/describeApi';
import type {
  DescriptionHistoryItem,
  DescriptionHistoryResponse,
  DescribeRunItem,
  DescribeRunItemsResponse,
} from '../../api/describeApi';
import { buildTestQueryClient, createQueryWrapper } from '../../test-utils/queryClient';
import { queryKeys } from '../../api/queryKeys';

vi.mock('../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/describeApi')>('../../api/describeApi');
  return {
    ...actual,
    fetchDescribeRunItems: vi.fn(),
    fetchDescribeRuns: vi.fn(),
    fetchDescriptionHistory: vi.fn(),
    applyDescribeRunDrafts: vi.fn(),
    correctDescriptionHistoryItem: vi.fn(),
  };
});

const fetchRunItemsMock = vi.mocked(describeApi.fetchDescribeRunItems);
const fetchHistoryMock = vi.mocked(describeApi.fetchDescriptionHistory);
const applyRunMock = vi.mocked(describeApi.applyDescribeRunDrafts);
const correctMock = vi.mocked(describeApi.correctDescriptionHistoryItem);

const runItem = (overrides: Partial<DescribeRunItem> = {}): DescribeRunItem => ({
  media_id: 71,
  status: 'completed',
  alt_text_draft: 'A flower.',
  caption: 'A flower.',
  provenance: null,
  tier: 'final_gpu',
  result_generation: 1,
  existing_alt: false,
  ...overrides,
});

const runResponse = (items: DescribeRunItem[]): DescribeRunItemsResponse => ({
  run_id: 'run-abc',
  items,
});

const historyItem = (overrides: Partial<DescriptionHistoryItem> = {}): DescriptionHistoryItem => ({
  media_id: 71,
  title: 'Flower',
  mime_type: 'image/jpeg',
  current_alt_text: '',
  generated_alt_text: 'A flower.',
  provenance: null,
  human_edit: null,
  run_status: null,
  is_decorative: false,
  ...overrides,
});

const historyResponse = (items: DescriptionHistoryItem[], total = items.length): DescriptionHistoryResponse => ({
  total,
  items,
});

describe('useQueueDrafts', () => {
  it('refreshes existing proposals after curation sync drains without submitting or applying a run', async () => {
    client.setQueryData(queryKeys.sync.health(), {
      outbox: { state: 'ok', pending: 1 },
      last_pull: { at: 'before', ok: true },
    });
    vi.mocked(describeApi.fetchDescribeRuns).mockResolvedValue({
      items: [{ run_id: 'run-abc', created_at: 200, media_ids: [71] }],
      total: 1,
      next_offset: null,
    });
    fetchRunItemsMock.mockResolvedValue(runResponse([runItem({ alt_text_draft: 'A woman waves.' })]));
    const { result } = renderHook(() => useQueueDrafts([71]), { wrapper });
    await waitFor(() => expect(result.current.draftsByMediaId[71]?.draftText).toBe('A woman waves.'));
    fetchRunItemsMock.mockResolvedValue(runResponse([runItem({ alt_text_draft: 'Ada waves.' })]));
    act(() => {
      client.setQueryData(queryKeys.sync.health(), {
        outbox: { state: 'ok', pending: 0 },
        last_pull: { at: 'after', ok: true },
      });
    });
    await waitFor(() => expect(result.current.draftsByMediaId[71]?.draftText).toBe('Ada waves.'));
    expect(applyRunMock).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();
  });

  it('loads older pages explicitly and keeps an old selected run distinct from the latest', async () => {
    vi.mocked(describeApi.fetchDescribeRuns).mockImplementation((_ids, offset) =>
      Promise.resolve({
        items: [
          { run_id: offset === 0 ? 'new-run' : 'old-run', created_at: offset === 0 ? 200 : 100, media_ids: [71] },
        ],
        total: 2,
        next_offset: offset === 0 ? 1 : null,
      }),
    );
    fetchRunItemsMock.mockImplementation((id) =>
      Promise.resolve({ run_id: id, items: [runItem({ alt_text_draft: id + ' draft' })] }),
    );
    const { result } = renderHook(() => useQueueDrafts([71], 'old-run'), { wrapper });
    await waitFor(() => expect(result.current.draftsByMediaId[71]?.runId).toBe('old-run'));
    expect(result.current.hasOlderDescriptions).toBe(true);
    result.current.loadOlderDescriptions();
    await waitFor(() => expect(result.current.hasOlderDescriptions).toBe(false));
    expect(result.current.historyByMediaId[71].map((draft) => draft.runId)).toEqual(['new-run', 'old-run']);
    expect(result.current.draftsByMediaId[71]?.runId).toBe('old-run');
    expect(correctMock).not.toHaveBeenCalled();
  });

  it('keeps available drafts while reporting a failed historical run read', async () => {
    vi.mocked(describeApi.fetchDescribeRuns).mockResolvedValue({
      items: [
        { run_id: 'new-run', created_at: 200, media_ids: [71] },
        { run_id: 'lost-run', created_at: 100, media_ids: [71] },
      ],
      total: 2,
      next_offset: null,
    });
    fetchHistoryMock.mockResolvedValue(historyResponse([]));
    fetchRunItemsMock.mockImplementation((id) =>
      id === 'lost-run' ? Promise.reject(new Error('unavailable')) : Promise.resolve(runResponse([runItem()])),
    );
    const { result } = renderHook(() => useQueueDrafts([71]), { wrapper });
    await waitFor(() => expect(result.current.historyPartial).toBe(true));
    expect(result.current.draftsByMediaId[71]?.draftText).toBe('A flower.');
    expect(result.current.isError).toBe(false);
  });

  it('discovers unapplied drafts on ordinary rows and keeps previous run versions', async () => {
    vi.mocked(describeApi.fetchDescribeRuns).mockResolvedValue({
      items: [
        { run_id: 'new-run', created_at: 200, media_ids: [71] },
        { run_id: 'old-run', created_at: 100, media_ids: [71] },
      ],
      total: 2,
      next_offset: null,
    });
    fetchHistoryMock.mockResolvedValue(historyResponse([]));
    fetchRunItemsMock.mockImplementation((id) =>
      Promise.resolve({
        run_id: id,
        items: [runItem({ alt_text_draft: id === 'new-run' ? 'New draft.' : 'Earlier draft.' })],
      }),
    );
    const { result } = renderHook(() => useQueueDrafts([71]), { wrapper });
    await waitFor(() => expect(result.current.draftsByMediaId[71]?.draftText).toBe('New draft.'));
    expect(result.current.historyByMediaId[71].map((draft) => draft.draftText)).toEqual([
      'New draft.',
      'Earlier draft.',
    ]);
    expect(applyRunMock).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();
  });

  let client: QueryClient;
  let wrapper: ReturnType<typeof createQueryWrapper>;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(describeApi.fetchDescribeRuns).mockResolvedValue({ items: [], total: 0, next_offset: null });
    client = buildTestQueryClient();
    wrapper = createQueryWrapper(client);
  });

  afterEach(() => {
    void client.cancelQueries();
    client.clear();
    cleanup();
  });

  it('does not fetch when no media ids are provided', () => {
    renderHook(() => useQueueDrafts([]), { wrapper });
    renderHook(() => useQueueDrafts([], 'run-abc'), { wrapper });

    expect(fetchRunItemsMock).not.toHaveBeenCalled();
    expect(fetchHistoryMock).not.toHaveBeenCalled();
    expect(applyRunMock).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();
  });

  it('keeps historyTruncated false when no media ids are provided', () => {
    const { result } = renderHook(() => useQueueDrafts([]), { wrapper });
    expect(result.current.historyTruncated).toBe(false);
  });

  it('reads run items when runId is set and keys usable drafts by media id', async () => {
    fetchRunItemsMock.mockResolvedValue(
      runResponse([
        runItem({ media_id: 71, alt_text_draft: 'A flower.', existing_alt: false }),
        runItem({ media_id: 70, alt_text_draft: 'A bridge.', existing_alt: true }),
        runItem({ media_id: 72, alt_text_draft: null, status: 'failed' }),
        runItem({ media_id: 73, alt_text_draft: '   ' }),
        runItem({ media_id: 99, alt_text_draft: 'Not on this page.' }),
      ]),
    );

    const { result } = renderHook(() => useQueueDrafts([71, 70, 72, 73], 'run-abc'), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(fetchRunItemsMock).toHaveBeenCalledWith('run-abc');
    expect(fetchHistoryMock).not.toHaveBeenCalled();
    expect(applyRunMock).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();

    expect(Object.keys(result.current.draftsByMediaId).map(Number).sort()).toEqual([70, 71]);
    expect(result.current.draftsByMediaId[71]).toEqual({
      mediaId: 71,
      draftText: 'A flower.',
      existingAlt: false,
      runId: 'run-abc',
      source: QUEUE_DRAFT_SOURCE.DESCRIBE_RUN,
    });
    expect(result.current.draftsByMediaId[70]?.existingAlt).toBe(true);
    expect(result.current.draftsByMediaId[72]).toBeUndefined();
    expect(result.current.draftsByMediaId[73]).toBeUndefined();
    expect(result.current.draftsByMediaId[99]).toBeUndefined();
    expect(result.current.historyTruncated).toBe(false);
  });

  it('reads description history when runId is omitted and skips applied or corrected rows', async () => {
    fetchHistoryMock.mockResolvedValue(
      historyResponse([
        historyItem({ media_id: 71, generated_alt_text: 'A flower.', current_alt_text: '' }),
        historyItem({
          media_id: 70,
          generated_alt_text: 'A bridge.',
          current_alt_text: 'Old library alt',
        }),
        historyItem({
          media_id: 74,
          generated_alt_text: 'Already applied.',
          current_alt_text: 'Already applied.',
        }),
        historyItem({
          media_id: 75,
          generated_alt_text: 'Human overrode this.',
          current_alt_text: 'Operator text',
          human_edit: { alt_text: 'Operator text', edited_at: '2026-09-18 12:00:00', user_id: 7 },
        }),
        historyItem({ media_id: 76, generated_alt_text: '', current_alt_text: '' }),
        historyItem({ media_id: 99, generated_alt_text: 'Other page.', current_alt_text: '' }),
      ]),
    );

    const { result } = renderHook(() => useQueueDrafts([71, 70, 74, 75, 76]), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(fetchHistoryMock).toHaveBeenCalledTimes(1);
    expect(fetchHistoryMock).toHaveBeenCalledWith({
      limit: QUEUE_DRAFTS_HISTORY_PAGE_SIZE,
      offset: 0,
    });
    expect(fetchRunItemsMock).not.toHaveBeenCalled();
    expect(applyRunMock).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();

    expect(Object.keys(result.current.draftsByMediaId).map(Number).sort()).toEqual([70, 71]);
    expect(result.current.draftsByMediaId[71]).toEqual({
      mediaId: 71,
      draftText: 'A flower.',
      existingAlt: false,
      runId: null,
      source: QUEUE_DRAFT_SOURCE.DESCRIPTION_HISTORY,
    });
    expect(result.current.draftsByMediaId[70]?.existingAlt).toBe(true);
    expect(result.current.draftsByMediaId[74]).toBeUndefined();
    expect(result.current.draftsByMediaId[75]).toBeUndefined();
    expect(result.current.historyTruncated).toBe(false);
  });

  it('decodes stored history alts at the read boundary', async () => {
    const storedGenerated = 'x ' + '&lt;' + '= y';
    fetchHistoryMock.mockResolvedValue(
      historyResponse([
        historyItem({
          media_id: 71,
          generated_alt_text: storedGenerated,
          current_alt_text: '',
        }),
      ]),
    );

    const { result } = renderHook(() => useQueueDrafts([71]), {
      wrapper,
    });

    await waitFor(() => expect(result.current.draftsByMediaId[71]).toBeDefined());
    expect(result.current.draftsByMediaId[71]?.draftText).toBe('x <= y');
  });

  it('never auto-applies after drafts resolve [HAI-04]', async () => {
    fetchRunItemsMock.mockResolvedValue(runResponse([runItem()]));

    const { result } = renderHook(() => useQueueDrafts([71], 'run-abc'), {
      wrapper,
    });

    await waitFor(() => expect(result.current.draftsByMediaId[71]).toBeDefined());

    expect(applyRunMock).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();
    expect(result.current.historyTruncated).toBe(false);
  });

  it('finds a wanted draft on page 2 and calls offsets 0 then 50', async () => {
    fetchHistoryMock.mockImplementation(async ({ offset = 0 } = {}) => {
      if (offset === 0) {
        return historyResponse([historyItem({ media_id: 1, generated_alt_text: 'Filler.' })], 100);
      }
      if (offset === QUEUE_DRAFTS_HISTORY_PAGE_SIZE) {
        return historyResponse([historyItem({ media_id: 71, generated_alt_text: 'A flower.' })], 100);
      }
      throw new Error(`unexpected offset ${offset}`);
    });

    const { result } = renderHook(() => useQueueDrafts([71]), {
      wrapper,
    });

    await waitFor(() => expect(result.current.draftsByMediaId[71]).toBeDefined());

    expect(fetchHistoryMock).toHaveBeenCalledTimes(2);
    expect(fetchHistoryMock).toHaveBeenNthCalledWith(1, {
      limit: QUEUE_DRAFTS_HISTORY_PAGE_SIZE,
      offset: 0,
    });
    expect(fetchHistoryMock).toHaveBeenNthCalledWith(2, {
      limit: QUEUE_DRAFTS_HISTORY_PAGE_SIZE,
      offset: QUEUE_DRAFTS_HISTORY_PAGE_SIZE,
    });
    expect(result.current.draftsByMediaId[71]?.draftText).toBe('A flower.');
    expect(result.current.historyTruncated).toBe(false);
  });

  it('stops paging once every wanted id has a usable draft', async () => {
    fetchHistoryMock.mockImplementation(async ({ offset = 0 } = {}) => {
      if (offset === 0) {
        return historyResponse([historyItem({ media_id: 71, generated_alt_text: 'A flower.' })], 200);
      }
      if (offset === QUEUE_DRAFTS_HISTORY_PAGE_SIZE) {
        return historyResponse([historyItem({ media_id: 70, generated_alt_text: 'A bridge.' })], 200);
      }
      throw new Error(`unexpected offset ${offset}`);
    });

    const { result } = renderHook(() => useQueueDrafts([71, 70]), {
      wrapper,
    });

    await waitFor(() => expect(result.current.draftsByMediaId[70]).toBeDefined());

    expect(fetchHistoryMock).toHaveBeenCalledTimes(2);
    expect(result.current.draftsByMediaId[71]?.draftText).toBe('A flower.');
    expect(result.current.draftsByMediaId[70]?.draftText).toBe('A bridge.');
    expect(result.current.historyTruncated).toBe(false);
  });

  it('stops paging once offset reaches total', async () => {
    fetchHistoryMock.mockImplementation(async ({ offset = 0 } = {}) => {
      if (offset === 0) {
        return historyResponse([historyItem({ media_id: 1, generated_alt_text: 'Filler.' })], 75);
      }
      if (offset === QUEUE_DRAFTS_HISTORY_PAGE_SIZE) {
        return historyResponse([historyItem({ media_id: 2, generated_alt_text: 'More filler.' })], 75);
      }
      throw new Error(`unexpected offset ${offset}`);
    });

    const { result } = renderHook(() => useQueueDrafts([71]), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(fetchHistoryMock).toHaveBeenCalledTimes(2);
    expect(result.current.draftsByMediaId[71]).toBeUndefined();
    expect(result.current.historyTruncated).toBe(false);
  });

  it('stops paging when a page returns zero items', async () => {
    fetchHistoryMock.mockImplementation(async ({ offset = 0 } = {}) => {
      if (offset === 0) {
        return historyResponse([historyItem({ media_id: 1, generated_alt_text: 'Filler.' })], 500);
      }
      if (offset === QUEUE_DRAFTS_HISTORY_PAGE_SIZE) {
        return historyResponse([], 500);
      }
      throw new Error(`unexpected offset ${offset}`);
    });

    const { result } = renderHook(() => useQueueDrafts([71]), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(fetchHistoryMock).toHaveBeenCalledTimes(2);
    expect(result.current.draftsByMediaId[71]).toBeUndefined();
    expect(result.current.historyTruncated).toBe(false);
  });

  it('stops at the page cap and sets historyTruncated when ids remain uncovered', async () => {
    const total = QUEUE_DRAFTS_HISTORY_MAX_PAGES * QUEUE_DRAFTS_HISTORY_PAGE_SIZE + 50;
    fetchHistoryMock.mockImplementation(async ({ offset = 0 } = {}) =>
      historyResponse([historyItem({ media_id: 1, generated_alt_text: `Filler at ${offset}.` })], total),
    );

    const { result } = renderHook(() => useQueueDrafts([71]), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(fetchHistoryMock).toHaveBeenCalledTimes(QUEUE_DRAFTS_HISTORY_MAX_PAGES);
    expect(result.current.draftsByMediaId[71]).toBeUndefined();
    expect(result.current.historyTruncated).toBe(true);
  });

  it('keeps the newest usable draft when the same id appears on a later page', async () => {
    fetchHistoryMock.mockImplementation(async ({ offset = 0 } = {}) => {
      if (offset === 0) {
        return historyResponse([historyItem({ media_id: 71, generated_alt_text: 'Newest flower.' })], 100);
      }
      if (offset === QUEUE_DRAFTS_HISTORY_PAGE_SIZE) {
        return historyResponse(
          [
            historyItem({ media_id: 71, generated_alt_text: 'Older flower.' }),
            historyItem({ media_id: 70, generated_alt_text: 'A bridge.' }),
          ],
          100,
        );
      }
      throw new Error(`unexpected offset ${offset}`);
    });

    const { result } = renderHook(() => useQueueDrafts([71, 70]), {
      wrapper,
    });

    await waitFor(() => expect(result.current.draftsByMediaId[70]).toBeDefined());

    expect(fetchHistoryMock).toHaveBeenCalledTimes(2);
    expect(result.current.draftsByMediaId[71]?.draftText).toBe('Newest flower.');
    expect(result.current.draftsByMediaId[70]?.draftText).toBe('A bridge.');
    expect(result.current.historyTruncated).toBe(false);
  });

  it('refetches history when the wanted media ids change', async () => {
    fetchHistoryMock.mockImplementation(async ({ offset = 0 } = {}) => {
      if (offset !== 0) {
        return historyResponse([], 2);
      }
      return historyResponse(
        [
          historyItem({ media_id: 71, generated_alt_text: 'A flower.' }),
          historyItem({ media_id: 70, generated_alt_text: 'A bridge.' }),
        ],
        2,
      );
    });

    const { result, rerender } = renderHook(({ mediaIds }: { mediaIds: number[] }) => useQueueDrafts(mediaIds), {
      wrapper,
      initialProps: { mediaIds: [71] },
    });

    await waitFor(() => expect(result.current.draftsByMediaId[71]).toBeDefined());
    expect(fetchHistoryMock).toHaveBeenCalledTimes(1);
    expect(result.current.draftsByMediaId[70]).toBeUndefined();

    rerender({ mediaIds: [70] });

    await waitFor(() => expect(result.current.draftsByMediaId[70]).toBeDefined());
    expect(fetchHistoryMock).toHaveBeenCalledTimes(2);
    expect(result.current.draftsByMediaId[71]).toBeUndefined();
    expect(result.current.draftsByMediaId[70]?.draftText).toBe('A bridge.');
  });

  it('does not page history when a runId is given', async () => {
    fetchRunItemsMock.mockResolvedValue(runResponse([runItem()]));
    fetchHistoryMock.mockResolvedValue(historyResponse([historyItem()], 500));

    const { result } = renderHook(() => useQueueDrafts([71], 'run-abc'), {
      wrapper,
    });

    await waitFor(() => expect(result.current.draftsByMediaId[71]).toBeDefined());

    expect(fetchRunItemsMock).toHaveBeenCalledTimes(1);
    expect(fetchHistoryMock).not.toHaveBeenCalled();
    expect(result.current.draftsByMediaId[71]?.source).toBe(QUEUE_DRAFT_SOURCE.DESCRIBE_RUN);
    expect(result.current.historyTruncated).toBe(false);
  });
});
