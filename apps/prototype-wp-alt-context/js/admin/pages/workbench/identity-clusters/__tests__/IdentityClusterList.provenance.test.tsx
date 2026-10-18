// Loader data and mutation boundaries are fixtures. HTTP cannot distinguish this
// singleton's legacy assignment from explicit provenance; observe the callback.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { DetectedIdentity } from '../../../../api/recognition';
import { IdentityClusterList } from '../IdentityClusterList';
import type { ProjectedSuggestion } from '../suggestionProjection';

const observed = vi.hoisted(() => ({
  confirm: vi.fn(),
  assign: vi.fn(),
  merge: vi.fn(),
  create: vi.fn(),
  rename: vi.fn(),
  rows: [] as ProjectedSuggestion[],
}));

vi.mock('../useClusterSuggestionsLoader', () => ({
  useClusterSuggestionsLoader: () => ({
    identityProjection: observed.rows,
    namingOptions: [{ value: 'cluster:manual-target', label: 'Manual choice', source: 'cluster', identityCount: 1 }],
    collisionsByLabel: new Map(),
    isLoading: false,
    findClusterByLabel: vi.fn().mockResolvedValue(null),
    atRestTotal: 1,
    atRestTruncated: false,
    isAtRestMode: true,
  }),
}));

// Observe the List callback boundary while retaining the real confirm/save hooks.
vi.mock('../useClusterSaveHandlers', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../useClusterSaveHandlers')>();
  return {
    ...actual,
    useClusterSaveHandlers: (options: Parameters<typeof actual.useClusterSaveHandlers>[0]) => {
      const handlers = actual.useClusterSaveHandlers(options);
      return {
        ...handlers,
        handleConfirmSuggestion: (...args: Parameters<typeof handlers.handleConfirmSuggestion>) => {
          observed.confirm(...args);
          return handlers.handleConfirmSuggestion(...args);
        },
      };
    },
  };
});

vi.mock('../useClusterMutations', () => ({
  useClusterMutations: () => ({
    isPending: false,
    isReverting: false,
    assignToCluster: observed.assign,
    merge: observed.merge,
    createClusterForIdentity: observed.create,
    rename: observed.rename,
    revertMerge: vi.fn(),
    rejectSuggestion: vi.fn(),
  }),
}));

vi.mock('../useInlineSuggestionBatch', () => ({
  useInlineSuggestionBatch: () => ({ getMatch: () => undefined }),
}));
vi.mock('../usePendingMergeTwins', () => ({
  usePendingMergeTwins: () => ({
    mergeSuggestions: [],
    truncated: false,
    scheduleAcceptMerge: vi.fn(),
    scheduleRejectMerge: vi.fn(),
    isCardPending: () => false,
  }),
}));

const FACE_ID = 'selected-residue-face';
const TARGET_ID = 'selected-target';
const SUGGESTION_ID = 'selected-pending-row';
const TARGET_LABEL = 'Selected person';
const member: DetectedIdentity = {
  identity_id: FACE_ID,
  representative_id: 'rep-selected',
  media_id: 115,
  cluster_id: null,
  cluster_label: null,
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 0.49,
  detected_at: '',
};

let client: QueryClient;

beforeEach(() => {
  vi.clearAllMocks();
  observed.rows = [
    {
      suggestionId: 'other-row',
      identityId: FACE_ID,
      clusterId: 'other-target',
      label: 'Other person',
      similarity: 0.7,
      identityCount: 1,
    },
    {
      suggestionId: SUGGESTION_ID,
      identityId: FACE_ID,
      clusterId: TARGET_ID,
      label: TARGET_LABEL,
      similarity: 0.49,
      identityCount: 1,
    },
  ];
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  client.clear();
});

const openEditor = () => {
  render(
    <QueryClientProvider client={client}>
      <IdentityClusterList identities={[member]} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Find similar / Name' }));
  const input = screen.getByRole('combobox');
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  return input;
};

const selectChoice = async (label: string) => {
  fireEvent.click(await screen.findByRole('option', { name: new RegExp(label) }));
  expect(screen.getByRole('combobox')).toHaveValue(label);
};

const expectNoWrites = () => {
  expect(observed.assign).not.toHaveBeenCalled();
  expect(observed.merge).not.toHaveBeenCalled();
  expect(observed.create).not.toHaveBeenCalled();
  expect(observed.rename).not.toHaveBeenCalled();
};

describe('IdentityClusterList residue provenance (render -> real option producer -> callback)', () => {
  it('preserves the selected row target, suggestion and source identity at the callback and assigns exactly once', async () => {
    openEditor();
    expectNoWrites();
    await selectChoice(TARGET_LABEL);
    expect(observed.confirm).not.toHaveBeenCalled();
    expectNoWrites();

    fireEvent.click(screen.getByRole('button', { name: 'Save name' }));

    expect(observed.confirm).toHaveBeenCalledExactlyOnceWith(TARGET_ID, TARGET_LABEL, SUGGESTION_ID, {
      kind: 'identity',
      identityId: FACE_ID,
    });
    await waitFor(() =>
      expect(observed.assign).toHaveBeenCalledExactlyOnceWith(
        FACE_ID,
        TARGET_ID,
        expect.any(AbortSignal),
        SUGGESTION_ID,
      ),
    );
    expect(observed.merge).not.toHaveBeenCalled();
    expect(observed.create).not.toHaveBeenCalled();
    expect(observed.rename).not.toHaveBeenCalled();
  });

  it('preserves ordinary unkeyed manual cluster choice', async () => {
    openEditor();
    await selectChoice('Manual choice');
    expectNoWrites();
    fireEvent.click(screen.getByRole('button', { name: 'Save name' }));

    expect(observed.confirm).toHaveBeenCalledTimes(1);
    expect(observed.confirm.mock.calls[0]?.slice(0, 3)).toEqual(['manual-target', 'Manual choice', undefined]);
    expect(observed.confirm.mock.calls[0]?.[3]).toBeUndefined();
    await waitFor(() =>
      expect(observed.assign).toHaveBeenCalledExactlyOnceWith(
        FACE_ID,
        'manual-target',
        expect.any(AbortSignal),
        undefined,
      ),
    );
    expect(observed.merge).not.toHaveBeenCalled();
  });

  it('cancels a filled keyed choice without confirming or writing', async () => {
    openEditor();
    await selectChoice(TARGET_LABEL);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(observed.confirm).not.toHaveBeenCalled();
    expectNoWrites();
  });
});
