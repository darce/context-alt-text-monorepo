import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QUEUE_DRAFT_SOURCE, useQueueDrafts } from '../useQueueDrafts';
import * as describeApi from '../../api/describeApi';
import type {
  DescriptionHistoryItem,
  DescriptionHistoryResponse,
  DescribeRunItem,
  DescribeRunItemsResponse,
} from '../../api/describeApi';

vi.mock('../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/describeApi')>('../../api/describeApi');
  return {
    ...actual,
    fetchDescribeRunItems: vi.fn(),
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

const historyResponse = (items: DescriptionHistoryItem[]): DescriptionHistoryResponse => ({
  total: items.length,
  items,
});

const buildClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

const createWrapper = (client: QueryClient) => {
  const Wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

describe('useQueueDrafts', () => {
  let client: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = buildClient();
  });

  afterEach(() => {
    void client.cancelQueries();
    client.clear();
    cleanup();
  });

  it('does not fetch when no media ids are provided', () => {
    renderHook(() => useQueueDrafts([]), { wrapper: createWrapper(client) });
    renderHook(() => useQueueDrafts([], 'run-abc'), { wrapper: createWrapper(client) });

    expect(fetchRunItemsMock).not.toHaveBeenCalled();
    expect(fetchHistoryMock).not.toHaveBeenCalled();
    expect(applyRunMock).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();
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
      wrapper: createWrapper(client),
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
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(fetchHistoryMock).toHaveBeenCalledWith({ limit: 50, offset: 0 });
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
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.draftsByMediaId[71]).toBeDefined());
    expect(result.current.draftsByMediaId[71]?.draftText).toBe('x <= y');
  });

  it('never auto-applies after drafts resolve [HAI-04]', async () => {
    fetchRunItemsMock.mockResolvedValue(runResponse([runItem()]));

    const { result } = renderHook(() => useQueueDrafts([71], 'run-abc'), {
      wrapper: createWrapper(client),
    });

    await waitFor(() => expect(result.current.draftsByMediaId[71]).toBeDefined());

    expect(applyRunMock).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();
  });
});
