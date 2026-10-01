// @vitest-environment jsdom
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDescribeMedia } from '../../hooks/useDescribeMedia';
import * as describeApi from '../describeApi';
import type { VisualFactsResponse } from '../describeApi';

vi.mock('../describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return { ...actual, describeMedia: vi.fn() };
});

const describeMediaMock = vi.mocked(describeApi.describeMedia);

const firstActionKey = '11111111-1111-4111-8111-111111111111';
const secondActionKey = '22222222-2222-4222-8222-222222222222';
const thirdActionKey = '33333333-3333-4333-8333-333333333333';

const sample: VisualFactsResponse = {
  tenant_id: '00000000-0000-4000-8000-000000000001',
  media_id: 42,
  image_hash: 'sha256:abc',
  context_hash: 'ctx',
  adapter: 'local_cpu',
  model_id: 'microsoft/Florence-2-base-ft',
  model_version: 'florence-2-base-ft',
  prompt_or_task_version: 'v1',
  visual_facts: { caption: 'A flower.', objects: ['flower'], ocr_text: null },
  alt_text_draft: 'A flower.',
  context_used: { sources: [], applied: false },
  provider_disclosure: { provider: 'local', left_service_boundary: false },
  cached: false,
  duration_ms: 13800,
  retention_class: 'retain_all',
  tier: 'provisional_cpu',
  result_generation: 1,
};

const wrapper = ({ children }: React.PropsWithChildren): React.ReactElement => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return React.createElement(QueryClientProvider, { client }, children);
};

describe('useDescribeMedia idempotency key', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const keys = [firstActionKey, secondActionKey, thirdActionKey];
    const cryptoMock = Object.create(globalThis.crypto) as Crypto;
    Object.defineProperty(cryptoMock, 'randomUUID', {
      configurable: true,
      value: vi.fn((): string => keys.shift() ?? secondActionKey),
    });
    vi.stubGlobal('crypto', cryptoMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reuses a retry key and mints a new key for each mutate or mutateAsync action', async () => {
    describeMediaMock.mockRejectedValueOnce(new Error('temporary network failure')).mockResolvedValue(sample);
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    act(() => result.current.mutate(42));
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(describeMediaMock.mock.calls[0]?.[1]?.idempotencyKey).toBe(firstActionKey);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(describeMediaMock).toHaveBeenCalledTimes(2);
    expect(describeMediaMock.mock.calls[1]?.[1]?.idempotencyKey).toBe(firstActionKey);

    act(() => result.current.mutate(42));
    await waitFor(() => expect(describeMediaMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(describeMediaMock.mock.calls[2]?.[1]?.idempotencyKey).toBe(secondActionKey);

    await act(async () => {
      await result.current.mutateAsync(42);
    });
    expect(describeMediaMock).toHaveBeenCalledTimes(4);
    expect(describeMediaMock.mock.calls[3]?.[1]?.idempotencyKey).toBe(thirdActionKey);
  });
});
