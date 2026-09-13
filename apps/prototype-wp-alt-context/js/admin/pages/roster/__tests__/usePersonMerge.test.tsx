import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import * as api from '../../../api/personMergeApi';
import { queryKeys } from '../../../api/queryKeys';
import { usePersonMerge } from '../../../hooks/usePersonMerge';

vi.mock('../../../api/personMergeApi', async importOriginal => ({
  ...await importOriginal<typeof import('../../../api/personMergeApi')>(),
  previewPersonMerge: vi.fn(), commitPersonMerge: vi.fn(), undoPersonMerge: vi.fn(),
}));

describe('usePersonMerge', () => {
  it('calls the APIs, retains the token, and invalidates both caches on commit and undo', async () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const request = { survivor_id: 1, loser_id: 2 };
    const preview = { survivor: { id: 1, name: 'Alice', cluster_count: 3 }, loser: { id: 2, name: 'Ally', cluster_count: 2 }, tags: ['friend'], conflicts: [] };
    vi.mocked(api.previewPersonMerge).mockResolvedValue(preview);
    vi.mocked(api.commitPersonMerge).mockResolvedValue({ survivor_id: 1, merged_cluster_ids: ['c'], undo_token: 'server-token' });
    vi.mocked(api.undoPersonMerge).mockResolvedValue({ restored_person_id: 2, restored_cluster_ids: ['c'] });
    const { result } = renderHook(usePersonMerge, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
    await act(async () => { await result.current.preview.mutateAsync(request); });
    expect(vi.mocked(api.previewPersonMerge).mock.calls[0][0]).toEqual(request);
    expect(result.current.preview.data).toEqual(preview);
    expect(invalidate).not.toHaveBeenCalled();
    await act(async () => { await result.current.commit.mutateAsync(request); });
    await waitFor(() => expect(result.current.undoToken).toBe('server-token'));
    expect(api.commitPersonMerge).toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.roster.all });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
    // IDCHIP-1-MUI-R-02: merge rebinds clusters to another person, so media
    // identity projections must be invalidated too, not just roster/clusters.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
    invalidate.mockClear();
    await act(async () => { await result.current.undo.mutateAsync('server-token'); });
    expect(api.undoPersonMerge).toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.roster.all });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
    expect(result.current.undoToken).toBe('server-token');
  });
});
