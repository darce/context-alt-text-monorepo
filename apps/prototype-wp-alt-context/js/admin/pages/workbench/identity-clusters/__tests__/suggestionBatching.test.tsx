import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { PendingSuggestion } from '../../../../api/recognition';
import { InlineSuggestionPrompt } from '../InlineSuggestionPrompt';
import {
  INLINE_SUGGESTION_BATCH_LIMIT,
  INLINE_SUGGESTION_BATCH_TIMEOUT_MS,
  reduceInlineSuggestionsByIdentity,
} from '../inlineSuggestionBatch';
import * as recognitionApi from '../../../../api/recognition';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/recognition', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../../api/recognition')>();
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
  };
});

const buildSuggestion = (
  overrides: Partial<PendingSuggestion> & Pick<PendingSuggestion, 'id' | 'identity_id'>,
): PendingSuggestion => ({
  suggested_cluster_id: 'cluster-1',
  representative_similarity: 0.9,
  cluster_label: 'Alice',
  cluster_identity_count: 3,
  ...overrides,
});

describe('reduceInlineSuggestionsByIdentity', () => {
  it('drops unlabeled-cluster rows and picks top-1 by similarity per identity', () => {
    const rows: PendingSuggestion[] = [
      buildSuggestion({
        id: 's1',
        identity_id: 'id-a',
        suggested_cluster_id: 'c-low',
        representative_similarity: 0.7,
        cluster_label: 'Alice',
      }),
      buildSuggestion({
        id: 's2',
        identity_id: 'id-a',
        suggested_cluster_id: 'c-high',
        representative_similarity: 0.95,
        cluster_label: 'Alicia',
      }),
      buildSuggestion({
        id: 's3',
        identity_id: 'id-b',
        suggested_cluster_id: 'c-unlabeled',
        representative_similarity: 0.99,
        cluster_label: null,
      }),
      buildSuggestion({
        id: 's4',
        identity_id: 'id-b',
        suggested_cluster_id: 'c-empty',
        representative_similarity: 0.98,
        cluster_label: '   ',
      }),
      buildSuggestion({
        id: 's5',
        identity_id: 'id-c',
        suggested_cluster_id: 'c-bob',
        representative_similarity: 0.88,
        cluster_label: 'Bob',
        cluster_identity_count: 12,
      }),
    ];

    const byIdentity = reduceInlineSuggestionsByIdentity(rows);

    expect(byIdentity.get('id-a')).toEqual({
      suggestion_id: 's2',
      cluster_id: 'c-high',
      label: 'Alicia',
      similarity: 0.95,
    });
    // id-b only had null/empty labels — absent means no labeled suggestion (AGT-10)
    expect(byIdentity.has('id-b')).toBe(false);
    expect(byIdentity.get('id-c')).toEqual({
      suggestion_id: 's5',
      cluster_id: 'c-bob',
      label: 'Bob',
      similarity: 0.88,
    });
  });
});

describe('InlineSuggestionPrompt batched query', () => {
  const createdClients: QueryClient[] = [];
  const createWrapper = () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    createdClients.push(queryClient);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { wrapper, queryClient };
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    createdClients.splice(0).forEach((client) => client.clear());
  });

  it('renders N identities with exactly one suggestions list request (limit=500)', async () => {
    const fetchPending = vi.mocked(recognitionApi.fetchPendingSuggestions);
    fetchPending.mockResolvedValue({
      suggestions: [
        buildSuggestion({
          id: 's1',
          identity_id: 'id-1',
          cluster_label: 'Alice',
          representative_similarity: 0.91,
          suggested_cluster_id: 'c-alice',
        }),
        buildSuggestion({
          id: 's2',
          identity_id: 'id-2',
          cluster_label: 'Bob',
          representative_similarity: 0.85,
          suggested_cluster_id: 'c-bob',
        }),
        buildSuggestion({
          id: 's3',
          identity_id: 'id-3',
          cluster_label: 'Carol',
          representative_similarity: 0.8,
          suggested_cluster_id: 'c-carol',
        }),
      ],
      limit: INLINE_SUGGESTION_BATCH_LIMIT,
      offset: 0,
      data_source: 'backend_proxy',
    });

    const { wrapper } = createWrapper();
    const onConfirm = vi.fn();
    const onReject = vi.fn();

    render(
      <>
        <InlineSuggestionPrompt identityId="id-1" onConfirm={onConfirm} onReject={onReject} isPending={false} />
        <InlineSuggestionPrompt identityId="id-2" onConfirm={onConfirm} onReject={onReject} isPending={false} />
        <InlineSuggestionPrompt identityId="id-3" onConfirm={onConfirm} onReject={onReject} isPending={false} />
      </>,
      { wrapper },
    );

    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument();
      expect(screen.getByText('Bob')).toBeInTheDocument();
      expect(screen.getByText('Carol')).toBeInTheDocument();
    });

    // K = ceil(P/500) with P <= 500 → 1 request for N cards (RES-15)
    expect(fetchPending).toHaveBeenCalledTimes(1);
    expect(fetchPending).toHaveBeenCalledWith(INLINE_SUGGESTION_BATCH_LIMIT, 0, INLINE_SUGGESTION_BATCH_TIMEOUT_MS);
  });

  it('pages through pending suggestions: exactly ceil(P/500) requests when P > 500', async () => {
    const fetchPending = vi.mocked(recognitionApi.fetchPendingSuggestions);
    const fullPage = Array.from({ length: INLINE_SUGGESTION_BATCH_LIMIT }, (_, i) =>
      buildSuggestion({
        id: `p1-${i}`,
        identity_id: `id-p1-${i}`,
        cluster_label: 'Page One',
        representative_similarity: 0.7,
      }),
    );
    fetchPending
      .mockResolvedValueOnce({
        suggestions: fullPage,
        limit: INLINE_SUGGESTION_BATCH_LIMIT,
        offset: 0,
        data_source: 'backend_proxy',
      })
      .mockResolvedValueOnce({
        suggestions: [
          buildSuggestion({
            id: 's-late',
            identity_id: 'id-late',
            suggested_cluster_id: 'c-late',
            cluster_label: 'Late Page Match',
            representative_similarity: 0.93,
          }),
        ],
        limit: INLINE_SUGGESTION_BATCH_LIMIT,
        offset: INLINE_SUGGESTION_BATCH_LIMIT,
        data_source: 'backend_proxy',
      });

    const { wrapper } = createWrapper();
    render(<InlineSuggestionPrompt identityId="id-late" onConfirm={vi.fn()} onReject={vi.fn()} isPending={false} />, {
      wrapper,
    });

    // Identity on page 2 still gets its prompt — no silent drop past the first page.
    await waitFor(() => expect(screen.getByText('Late Page Match')).toBeInTheDocument());
    expect(fetchPending).toHaveBeenCalledTimes(2);
    expect(fetchPending).toHaveBeenNthCalledWith(
      2,
      INLINE_SUGGESTION_BATCH_LIMIT,
      INLINE_SUGGESTION_BATCH_LIMIT,
      INLINE_SUGGESTION_BATCH_TIMEOUT_MS,
    );
  });

  it('renders nothing for an identity with no labeled suggestion (same empty state as today)', async () => {
    const fetchPending = vi.mocked(recognitionApi.fetchPendingSuggestions);
    fetchPending.mockResolvedValue({
      suggestions: [
        buildSuggestion({
          id: 's1',
          identity_id: 'id-other',
          cluster_label: 'Alice',
          representative_similarity: 0.9,
        }),
        buildSuggestion({
          id: 's2',
          identity_id: 'id-empty',
          cluster_label: null,
          representative_similarity: 0.99,
        }),
      ],
      limit: INLINE_SUGGESTION_BATCH_LIMIT,
      offset: 0,
      data_source: 'backend_proxy',
    });

    const { wrapper } = createWrapper();
    const { container } = render(
      <InlineSuggestionPrompt identityId="id-empty" onConfirm={vi.fn()} onReject={vi.fn()} isPending={false} />,
      { wrapper },
    );

    await waitFor(() => expect(fetchPending).toHaveBeenCalledTimes(1));
    // Loading finished + no match → null (honest empty; AGT-10)
    await waitFor(() => {
      expect(container.querySelector('.acx-inline-suggestion')).toBeNull();
    });
    expect(screen.queryByText('Is this')).not.toBeInTheDocument();
  });

  it('shows top match label and similarity for the selected identity', async () => {
    const fetchPending = vi.mocked(recognitionApi.fetchPendingSuggestions);
    fetchPending.mockResolvedValue({
      suggestions: [
        buildSuggestion({
          id: 's-low',
          identity_id: 'id-1',
          suggested_cluster_id: 'c-low',
          cluster_label: 'Low',
          representative_similarity: 0.6,
        }),
        buildSuggestion({
          id: 's-high',
          identity_id: 'id-1',
          suggested_cluster_id: 'c-high',
          cluster_label: 'High Match',
          representative_similarity: 0.87,
        }),
      ],
      limit: INLINE_SUGGESTION_BATCH_LIMIT,
      offset: 0,
      data_source: 'backend_proxy',
    });

    const { wrapper } = createWrapper();
    render(<InlineSuggestionPrompt identityId="id-1" onConfirm={vi.fn()} onReject={vi.fn()} isPending={false} />, {
      wrapper,
    });

    await waitFor(() => expect(screen.getByText('High Match')).toBeInTheDocument());
    expect(screen.getByText('87%')).toBeInTheDocument();
    expect(screen.queryByText('Low')).not.toBeInTheDocument();
  });
});
