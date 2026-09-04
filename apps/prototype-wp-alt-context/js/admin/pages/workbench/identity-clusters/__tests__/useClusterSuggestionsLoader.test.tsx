import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NAMING_OPTIONS_LIMIT } from '../buildNamingOptions';
import { useClusterSuggestionsLoader } from '../useClusterSuggestionsLoader';
import { ClusterLabelLookupError, lookupClusterByLabel, CLUSTER_LABEL_LOOKUP_STATUS } from '../clusterLabelLookup';
import * as recognitionApi from '../../../../api/recognition';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';
import { classifyError } from '../../../../utils/appError';
import { HTTPError } from '../../../../utils/http';
import { setLogSink, type LogRecord } from '../../../../utils/logger';

vi.mock('../../../../api/recognition', () => ({
  fetchIdentitiesSuggestions: vi.fn(),
  listRecognitionClusters: vi.fn(),
}));

vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

describe('useClusterSuggestionsLoader', () => {
  const createWrapper = () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { wrapper, queryClient };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
  });

  afterEach(() => {
    setLogSink(null);
  });

  const emptyIdentityBatch = () => {
    vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({
      matches: { 'identity-1': [] },
    });
    vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
      clusters: [],
      limit: 50,
      total: 0,
      truncated: false,
    });
  };

  const renderLoader = () => {
    const { wrapper, queryClient } = createWrapper();
    const hook = renderHook(
      () =>
        useClusterSuggestionsLoader({
          identityId: 'identity-1',
          enabled: true,
          labelInput: '',
          debounceMs: 0,
        }),
      { wrapper },
    );
    return { ...hook, queryClient };
  };

  it('caps at-rest namingOptions at NAMING_OPTIONS_LIMIT when the labelled page is larger', async () => {
    // Predicted first failure (limit: null): namingOptions has length 40.
    const { wrapper, queryClient } = createWrapper();
    vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({
      matches: { 'identity-1': [] },
    });
    const baseCluster = {
      member_ids: [],
      representative_identity: {
        media_id: null,
        bbox: { x: 0, y: 0, width: 0, height: 0 },
      },
      sample_identities: [],
    };
    const labeledPage = Array.from({ length: 40 }, (_, index) => ({
      ...baseCluster,
      id: `cluster-${index}`,
      label: `Labelled ${index}`,
      identity_count: 1,
    }));
    vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
      clusters: labeledPage,
      limit: 50,
      total: 40,
      truncated: false,
    });

    const { result } = renderHook(
      () =>
        useClusterSuggestionsLoader({
          identityId: 'identity-1',
          enabled: true,
          labelInput: '',
          debounceMs: 0,
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.atRestTotal).toBe(40));
    expect(result.current.isAtRestMode).toBe(true);
    expect(result.current.namingOptions).toHaveLength(NAMING_OPTIONS_LIMIT);
    expect(result.current.namingOptions.length).not.toBe(40);

    queryClient.clear();
  });

  it('findClusterByLabel short-circuits DOMException AbortError without logging', async () => {
    emptyIdentityBatch();
    const { result, queryClient } = renderLoader();
    await waitFor(() => expect(result.current.findClusterByLabel).toEqual(expect.any(Function)));

    vi.mocked(recognitionApi.listRecognitionClusters).mockRejectedValue(
      new DOMException('The operation was aborted.', 'AbortError'),
    );
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    await expect(result.current.findClusterByLabel('Alice')).resolves.toBeNull();
    expect(consoleWarn).not.toHaveBeenCalled();
    expect(records.filter((record) => record.level === 'warn')).toHaveLength(0);

    consoleWarn.mockRestore();
    queryClient.clear();
  });

  it('findClusterByLabel short-circuits pre-classified abort AppError [CARD-24]', async () => {
    emptyIdentityBatch();
    const { result, queryClient } = renderLoader();
    await waitFor(() => expect(result.current.findClusterByLabel).toEqual(expect.any(Function)));

    vi.mocked(recognitionApi.listRecognitionClusters).mockRejectedValue(
      classifyError(new DOMException('The operation was aborted.', 'AbortError')),
    );
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    await expect(result.current.findClusterByLabel('Alice')).resolves.toBeNull();
    expect(consoleWarn).not.toHaveBeenCalled();
    expect(records.filter((record) => record.level === 'warn')).toHaveLength(0);

    consoleWarn.mockRestore();
    queryClient.clear();
  });

  it('findClusterByLabel short-circuits non-DOMException TimeoutError abort [CARD-24]', async () => {
    emptyIdentityBatch();
    const { result, queryClient } = renderLoader();
    await waitFor(() => expect(result.current.findClusterByLabel).toEqual(expect.any(Function)));

    const timeoutErr = new Error('The operation timed out.');
    timeoutErr.name = 'TimeoutError';
    vi.mocked(recognitionApi.listRecognitionClusters).mockRejectedValue(timeoutErr);
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    await expect(result.current.findClusterByLabel('Alice')).resolves.toBeNull();
    expect(consoleWarn).not.toHaveBeenCalled();
    expect(records.filter((record) => record.level === 'warn')).toHaveLength(0);

    consoleWarn.mockRestore();
    queryClient.clear();
  });

  it('findClusterByLabel logs classified {tag,status,endpoint} without bodyPreview [FEBT-1-W1-O-06]', async () => {
    emptyIdentityBatch();
    const { result, queryClient } = renderLoader();
    await waitFor(() => expect(result.current.findClusterByLabel).toEqual(expect.any(Function)));

    vi.mocked(recognitionApi.listRecognitionClusters).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters?search=Alice',
        bodyPreview: 'secret-body-preview-should-not-leak',
        message: 'server exploded secret-body-preview-should-not-leak',
      }),
    );
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    // FEBT1G-H-04: a lookup that could not RUN must not read as "name is free".
    await expect(result.current.findClusterByLabel('Alice')).rejects.toBeInstanceOf(ClusterLabelLookupError);
    expect(consoleWarn).not.toHaveBeenCalled();

    const warns = records.filter((record) => record.level === 'warn');
    expect(warns).toHaveLength(1);
    expect(warns[0]?.message).toBe('Failed to find cluster by label');
    expect(warns[0]?.fields.tag).toBe('http');
    expect(warns[0]?.fields.status).toBe(500);
    // FEBT1-LD-05: `toContain` passed identically before and after redaction, so it gated
    // nothing. Assert the exact redacted form — the `?search=Alice` query must be gone.
    expect(warns[0]?.fields.endpoint).toBe('/acx/v1/recognition/clusters');
    expect(JSON.stringify(warns[0])).not.toContain('Alice');
    expect(JSON.stringify(warns[0])).not.toContain('secret-body-preview-should-not-leak');
    expect(warns[0]?.fields).not.toHaveProperty('bodyPreview');

    consoleWarn.mockRestore();
    queryClient.clear();
  });

  it('lookupClusterByLabel reports lookup failure as a distinct status, not a null match [FEBT1G-H-04]', async () => {
    vi.mocked(recognitionApi.listRecognitionClusters).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters?search=Alice',
        bodyPreview: 'nope',
        message: 'server exploded',
      }),
    );
    const failed = await lookupClusterByLabel({ label: 'Alice', editableClusterId: null });
    expect(failed.status).toBe(CLUSTER_LABEL_LOOKUP_STATUS.LOOKUP_FAILED);

    vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
      clusters: [],
      total: 0,
      limit: 10,
      offset: 0,
    } as unknown as Awaited<ReturnType<typeof recognitionApi.listRecognitionClusters>>);
    const none = await lookupClusterByLabel({ label: 'Alice', editableClusterId: null });
    expect(none.status).toBe(CLUSTER_LABEL_LOOKUP_STATUS.NONE);

    // The two outcomes are distinguishable — that is the whole finding.
    expect(failed.status).not.toBe(none.status);
  });
});
