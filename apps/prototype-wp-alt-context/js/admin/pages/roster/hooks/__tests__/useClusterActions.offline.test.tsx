import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../../../api/recognition';
import * as rosterApi from '../../../../api/rosterApi';
import { useClusterActions } from '../useClusterActions';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('../../../../api/recognition', () => ({
  dismissCluster: vi.fn(),
  mergeCluster: vi.fn(),
  reassignClusterIdentity: vi.fn(),
  scanFacesBatched: vi.fn(),
}));

vi.mock('../../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn(),
}));

vi.mock('../../../../context/ToastContext', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

let offline = false;

vi.mock('../../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => offline,
}));

const wrapper = ({ children }: { children: ReactNode }) => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('useClusterActions rescan offline gate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    offline = false;
  });

  it('exposes enabled rescanGate online and allows rescan', async () => {
    vi.mocked(recognitionApi.scanFacesBatched).mockResolvedValue({
      jobs: [{ id: 'job-1' }],
    } as never);

    const { result } = renderHook(() => useClusterActions(), { wrapper });
    expect(result.current.rescanGate.disabled).toBe(false);
    expect(result.current.rescanGate.title).toBeUndefined();

    result.current.rescanMutation.mutate({
      cluster: { id: 'c1', sample_identities: [{ media_id: 1 }] },
      mediaIds: [1],
    });

    await waitFor(() => expect(recognitionApi.scanFacesBatched).toHaveBeenCalled());
  });

  it('exposes disabled rescanGate offline and refuses rescan', async () => {
    offline = true;
    const { result } = renderHook(() => useClusterActions(), { wrapper });

    expect(result.current.rescanGate.disabled).toBe(true);
    expect(result.current.rescanGate.title).toBe('Unavailable while the recognition service is offline');
    expect(result.current.rescanGate['aria-disabled']).toBe(true);

    result.current.rescanMutation.mutate({
      cluster: { id: 'c1', sample_identities: [{ media_id: 1 }] },
      mediaIds: [1],
    });

    await waitFor(() => expect(result.current.rescanMutation.isError).toBe(true));
    expect(recognitionApi.scanFacesBatched).not.toHaveBeenCalled();
  });
});

describe('useClusterActions commit invalidation (clusterLabelSetClear event)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    offline = false;
  });

  it('roster commit invalidates the suggestion projection alongside clusters + roster', async () => {
    // TEST-06 predicted first failure (pre-fix): invalidateQueries never called with
    // { queryKey: ['suggestions','projection'] } — commit only touched clusters.all + roster.entries.
    vi.mocked(rosterApi.commitClusterToRosterEntry).mockResolvedValue({
      cluster_id: 'c-1',
      person_id: 7,
      person_uuid: 'person-uuid-7',
      person_name: 'Entry',
      updated_at: '2026-01-01T00:00:00Z',
    });

    const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const clientWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useClusterActions(), { wrapper: clientWrapper });

    result.current.commitMutation.mutate({ clusterId: 'c-1', rosterEntryId: 7 });

    await waitFor(() => {
      expect(rosterApi.commitClusterToRosterEntry).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['suggestions', 'projection'] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['clusters'] });
    });
  });
});
