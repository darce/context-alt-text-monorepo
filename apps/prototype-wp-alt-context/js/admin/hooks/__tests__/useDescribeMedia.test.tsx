import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDescribeMedia } from '../useDescribeMedia';
import * as describeApi from '../../api/describeApi';
import type { VisualFactsResponse } from '../../api/describeApi';
import suggestStates from '../../pages/workbench/__tests__/fixtures/gpuflow-suggest-states.json';

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return {
    ...actual,
    describeMedia: vi.fn(),
  };
});

const describeMediaMock = vi.mocked(describeApi.describeMedia);

const describeErrorFromFixture = (fixture: { status: number; detail: object }): Error =>
  new Error(
    `Request to .../describe failed (${fixture.status}): ${JSON.stringify({ detail: fixture.detail })}`,
  );

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

const wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('useDescribeMedia', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls describeMedia with the media id and threads the result to data', async () => {
    describeMediaMock.mockResolvedValue(sample);
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate(42);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(describeMediaMock).toHaveBeenCalledWith(42);
    expect(result.current.data).toEqual(sample);
  });

  it('passes write intent options through to describeMedia', async () => {
    describeMediaMock.mockResolvedValue({
      ...sample,
      alt_text_write: { status: 'written', existing_alt_present: false },
    });
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate({ mediaId: 42, writeAlt: true });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(describeMediaMock).toHaveBeenCalledWith(42, { writeAlt: true, force: false });
    expect(result.current.data?.alt_text_write?.status).toBe('written');
  });

  it('threads a rejection to error state', async () => {
    describeMediaMock.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate(7);

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe('boom');
    expect(result.current.warming).toBeNull();
  });

  it('stores a starting lease and retry sends operation_id', async () => {
    describeMediaMock
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.starting_with_eta))
      .mockResolvedValueOnce(suggestStates.success_with_timing);
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate(42);

    await waitFor(() => expect(result.current.warming).not.toBeNull());
    expect(result.current.warming).toEqual({
      operationId: 'op-lease-1',
      warmupEtaSeconds: 12,
    });
    expect(describeMediaMock).toHaveBeenCalledWith(42);

    result.current.retry();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(describeMediaMock).toHaveBeenNthCalledWith(2, 42, { operationId: 'op-lease-1' });
    expect(result.current.warming).toBeNull();
    expect(result.current.timing).toEqual(suggestStates.success_with_timing.timing);
  });

  it('stores a null ETA from the wire and a null operationId when the starting envelope omits it', async () => {
    describeMediaMock
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.starting_no_eta))
      .mockRejectedValueOnce(
        describeErrorFromFixture({
          status: 503,
          detail: {
            code: 'description_service_starting',
            message: 'Description service is starting.',
            warmup_eta_seconds: 12,
          },
        }),
      );
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate(42);
    await waitFor(() => expect(result.current.warming).not.toBeNull());
    expect(result.current.warming).toEqual({
      operationId: 'op-lease-1',
      warmupEtaSeconds: null,
    });

    result.current.reset();
    result.current.mutate(42);
    await waitFor(() => expect(result.current.warming?.warmupEtaSeconds).toBe(12));
    expect(result.current.warming?.operationId).toBeNull();
  });

  it('retries mismatch once without operation_id, then surfaces a repeated mismatch', async () => {
    describeMediaMock
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.starting_with_eta))
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.mismatch))
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.mismatch));
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate(42);
    await waitFor(() => expect(result.current.warming?.operationId).toBe('op-lease-1'));

    result.current.retry();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(describeMediaMock).toHaveBeenNthCalledWith(2, 42, { operationId: 'op-lease-1' });
    expect(describeMediaMock).toHaveBeenNthCalledWith(3, 42);
    expect(describeMediaMock).toHaveBeenCalledTimes(3);
    expect(result.current.warming).toBeNull();
    expect(describeApi.resolveDescribeErrorCode(result.current.error)).toBe(
      describeApi.DESCRIBE_OPERATION_ERROR_CODE.MISMATCH,
    );
  });

  it('clears the lease on success after a mismatch retry without id', async () => {
    describeMediaMock
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.starting_with_eta))
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.mismatch))
      .mockResolvedValueOnce(suggestStates.success_no_timing);
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate(42);
    await waitFor(() => expect(result.current.warming).not.toBeNull());

    result.current.retry();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(describeMediaMock).toHaveBeenNthCalledWith(3, 42);
    expect(result.current.warming).toBeNull();
    expect(result.current.timing).toBeNull();
  });

  it('clears the lease on description_service_unavailable', async () => {
    describeMediaMock
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.starting_with_eta))
      .mockRejectedValueOnce(describeErrorFromFixture(suggestStates.unavailable));
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate(42);
    await waitFor(() => expect(result.current.warming).not.toBeNull());

    result.current.retry();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.warming).toBeNull();
    expect(result.current.timing).toBeNull();
  });

  it('exposes timing from the last success payload and null when the key is absent', async () => {
    describeMediaMock
      .mockResolvedValueOnce(suggestStates.success_with_timing)
      .mockResolvedValueOnce(suggestStates.success_no_timing);
    const { result } = renderHook(() => useDescribeMedia(), { wrapper });

    result.current.mutate(42);
    await waitFor(() => expect(result.current.timing).toEqual(suggestStates.success_with_timing.timing));

    result.current.mutate(42);
    await waitFor(() => expect(result.current.data).toEqual(suggestStates.success_no_timing));
    expect(result.current.timing).toBeNull();
  });
});
