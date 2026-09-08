import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDescribeMedia } from '../useDescribeMedia';
import * as describeApi from '../../api/describeApi';
import type { VisualFactsResponse } from '../../api/describeApi';

vi.mock('../../api/describeApi', () => ({ describeMedia: vi.fn() }));

const describeMediaMock = vi.mocked(describeApi.describeMedia);

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
  });
});
