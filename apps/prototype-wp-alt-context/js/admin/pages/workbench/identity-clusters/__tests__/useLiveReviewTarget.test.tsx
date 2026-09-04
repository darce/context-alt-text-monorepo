import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchClusterMembers } from '../../../../api/recognition';
import type { ClusterMembersResponse } from '../../../../api/recognition';
import { classifyError } from '../../../../utils/appError';
import { AuthExpiredError, HTTPError } from '../../../../utils/http';
import {
  LIVE_TARGET_CLOSE_ANNOUNCE,
  LIVE_TARGET_REBIND_ANNOUNCE,
  useLiveReviewTarget,
} from '../useLiveReviewTarget';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text
      .replace(/%(\d+)\$[sd]/g, (_match, group: string) => String(values[Number(group) - 1] ?? ''))
      .replace(/%[sd]/g, () => String(values[index++] ?? ''));
  },
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>(
    '../../../../api/recognition',
  );
  return {
    ...actual,
    fetchClusterMembers: vi.fn(),
  };
});

const notFound = (clusterId = 'x'): HTTPError =>
  new HTTPError({
    status: 404,
    retryAfterSeconds: undefined,
    endpoint: `/acx/v1/recognition/clusters/${clusterId}/members`,
    bodyPreview: 'cluster_not_found',
    message: 'cluster not found',
  });

const okMembers = (): ClusterMembersResponse => ({
  members: [
    {
      identity_id: 'id-1',
      media_id: 1,
      similarity: 0.9,
      confidence: 0.9,
      bbox: { x: 0, y: 0, width: 10, height: 10 },
      thumb_url: 'http://example.test/t.jpg',
    },
  ],
  limit: 1,
  total: 1,
  truncated: false,
});

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return wrapper;
};

describe('useLiveReviewTarget', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('stays live when the existence query succeeds', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(okMembers());
    const onClose = vi.fn();
    const onRebind = vi.fn();

    const { result } = renderHook(
      () => useLiveReviewTarget('cluster-live', { onClose, onRebind }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.status).toBe('live');
      expect(result.current.resolvedClusterId).toBe('cluster-live');
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(onRebind).not.toHaveBeenCalled();
    expect(fetchClusterMembers).toHaveBeenCalledWith('cluster-live', { limit: 1 });
  });

  it('branch (B): 404 with recorded survivor rebinds + announces once', async () => {
    vi.mocked(fetchClusterMembers).mockRejectedValue(notFound('cluster-x'));
    const onAnnounce = vi.fn();
    const onRebind = vi.fn();
    const onClose = vi.fn();

    const { result } = renderHook(
      () =>
        useLiveReviewTarget('cluster-x', {
          resolveSurvivor: (id) => (id === 'cluster-x' ? 'cluster-survivor' : null),
          onAnnounce,
          onRebind,
          onClose,
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.status).toBe('rebound');
    });
    expect(result.current.resolvedClusterId).toBe('cluster-survivor');
    expect(onRebind).toHaveBeenCalledTimes(1);
    expect(onRebind).toHaveBeenCalledWith('cluster-survivor');
    expect(onAnnounce).toHaveBeenCalledWith(LIVE_TARGET_REBIND_ANNOUNCE);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('BR-64: survivor recorded but no onRebind sink announces the close copy, never the rebind claim', async () => {
    vi.mocked(fetchClusterMembers).mockRejectedValue(notFound('cluster-x'));
    const onAnnounce = vi.fn();

    // Queue-head consumer shape: onAnnounce set, onRebind/onClose undefined. The
    // queue owns no bound pane, so it must not claim a rebind it cannot perform.
    const { result } = renderHook(
      () =>
        useLiveReviewTarget('cluster-x', {
          resolveSurvivor: (id) => (id === 'cluster-x' ? 'cluster-survivor' : null),
          onAnnounce,
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.status).toBe('rebound');
    });
    // Status still resolves the survivor (head suppression reads status), but the
    // announcement is the honest close copy — never the rebind claim.
    expect(result.current.resolvedClusterId).toBe('cluster-survivor');
    await waitFor(() => {
      expect(onAnnounce).toHaveBeenCalledWith(LIVE_TARGET_CLOSE_ANNOUNCE);
    });
    expect(onAnnounce).not.toHaveBeenCalledWith(LIVE_TARGET_REBIND_ANNOUNCE);
  });

  it('branch (A): 404 without survivor closes + announces once', async () => {
    vi.mocked(fetchClusterMembers).mockRejectedValue(notFound('cluster-x'));
    const onAnnounce = vi.fn();
    const onRebind = vi.fn();
    const onClose = vi.fn();

    const { result } = renderHook(
      () =>
        useLiveReviewTarget('cluster-x', {
          resolveSurvivor: () => null,
          onAnnounce,
          onRebind,
          onClose,
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.status).toBe('retired');
    });
    expect(result.current.resolvedClusterId).toBeNull();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onAnnounce).toHaveBeenCalledWith(LIVE_TARGET_CLOSE_ANNOUNCE);
    expect(onRebind).not.toHaveBeenCalled();
  });

  it('self-heal: wrong survivor guess rebinds then closes when survivor also 404s', async () => {
    vi.mocked(fetchClusterMembers).mockImplementation((clusterId) => {
      return Promise.reject(notFound(clusterId));
    });

    const announces: string[] = [];
    const rebinds: string[] = [];
    let openId: string | null = 'cluster-x';
    const survivors = new Map([['cluster-x', 'cluster-wrong']]);

    const { result, rerender } = renderHook(
      ({ id }: { id: string | null }) =>
        useLiveReviewTarget(id, {
          resolveSurvivor: (retired) => survivors.get(retired) ?? null,
          onAnnounce: (m) => announces.push(m),
          onRebind: (survivor) => {
            rebinds.push(survivor);
            openId = survivor;
          },
          onClose: () => {
            openId = null;
          },
        }),
      { wrapper: createWrapper(), initialProps: { id: openId } },
    );

    await waitFor(() => {
      expect(result.current.status).toBe('rebound');
    });
    expect(rebinds).toEqual(['cluster-wrong']);

    // Parent rebinds open id → remount path simulated via rerender.
    rerender({ id: 'cluster-wrong' });

    await waitFor(() => {
      expect(result.current.status).toBe('retired');
    });
    expect(announces).toEqual([LIVE_TARGET_REBIND_ANNOUNCE, LIVE_TARGET_CLOSE_ANNOUNCE]);
    expect(openId).toBeNull();
  });

  it('probe TimeoutError is not live and surfaces a non-null error [FEBT1-W2A-06]', async () => {
    const timeout = new DOMException('The operation timed out.', 'TimeoutError');
    vi.mocked(fetchClusterMembers).mockRejectedValue(timeout);
    const onClose = vi.fn();

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: true } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useLiveReviewTarget('cluster-timeout', { onClose }), {
      wrapper,
    });

    await waitFor(() => {
      expect(result.current.status).not.toBe('live');
      expect(result.current.error).not.toBeNull();
    });
    expect(result.current.status).toBe('unknown');
    expect(result.current.error).toBe(timeout);
    expect(result.current.resolvedClusterId).toBe('cluster-timeout');
    expect(onClose).not.toHaveBeenCalled();
    expect(fetchClusterMembers).toHaveBeenCalledTimes(1);
  });

  it('probe HTTP 500 is not live and surfaces a non-null error [FEBT1-W2A-06]', async () => {
    const serverError = new HTTPError({
      status: 500,
      retryAfterSeconds: undefined,
      endpoint: '/acx/v1/recognition/clusters/cluster-500/members',
      bodyPreview: 'internal boom',
      message: 'Request to /acx/v1/recognition/clusters/cluster-500/members failed (500): internal boom',
    });
    vi.mocked(fetchClusterMembers).mockRejectedValue(serverError);
    const onClose = vi.fn();

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: true } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useLiveReviewTarget('cluster-500', { onClose }), {
      wrapper,
    });

    await waitFor(() => {
      expect(result.current.status).not.toBe('live');
      expect(result.current.error).not.toBeNull();
    });
    expect(result.current.status).toBe('unknown');
    expect(result.current.error).toBe(serverError);
    expect(result.current.resolvedClusterId).toBe('cluster-500');
    expect(onClose).not.toHaveBeenCalled();
    expect(fetchClusterMembers).toHaveBeenCalledTimes(1);
  });

  it('AuthExpiredError is never retried and never absorbed into live [TEST-15]', async () => {
    const authExpired = new AuthExpiredError({
      endpoint: '/members',
      status: 403,
    });
    vi.mocked(fetchClusterMembers).mockRejectedValue(authExpired);
    const onClose = vi.fn();

    // Retry enabled so a bad predicate would re-fire the probe.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: true } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useLiveReviewTarget('cluster-auth', { onClose }), {
      wrapper,
    });

    await waitFor(() => {
      expect(result.current.status).toBe('auth_expired');
    });
    expect(result.current.status).not.toBe('live');
    expect(result.current.error).toBe(authExpired);
    expect(result.current.resolvedClusterId).toBe('cluster-auth');
    expect(onClose).not.toHaveBeenCalled();
    // Inline retry predicate returns false for AuthExpiredError → single probe.
    expect(fetchClusterMembers).toHaveBeenCalledTimes(1);
  });

  it('pre-classified AppError http 404 retires without retry [FEBT-1-W1-E-02]', async () => {
    const classified = classifyError(notFound('cluster-x'));
    vi.mocked(fetchClusterMembers).mockRejectedValue(classified);
    const onClose = vi.fn();
    const onAnnounce = vi.fn();

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: true } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(
      () =>
        useLiveReviewTarget('cluster-x', {
          resolveSurvivor: () => null,
          onAnnounce,
          onClose,
        }),
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.status).toBe('retired');
    });
    expect(result.current.resolvedClusterId).toBeNull();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onAnnounce).toHaveBeenCalledWith(LIVE_TARGET_CLOSE_ANNOUNCE);
    expect(fetchClusterMembers).toHaveBeenCalledTimes(1);
  });

  it('pre-classified AppError auth_expired is never retried and never absorbed into live [FEBT-1-W1-E-02]', async () => {
    const classified = classifyError(
      new AuthExpiredError({
        endpoint: '/members',
        status: 403,
      }),
    );
    vi.mocked(fetchClusterMembers).mockRejectedValue(classified);
    const onClose = vi.fn();

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: true } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useLiveReviewTarget('cluster-auth', { onClose }), {
      wrapper,
    });

    await waitFor(() => {
      expect(result.current.status).toBe('auth_expired');
    });
    expect(result.current.status).not.toBe('live');
    expect(result.current.error).toBe(classified);
    expect(result.current.resolvedClusterId).toBe('cluster-auth');
    expect(onClose).not.toHaveBeenCalled();
    expect(fetchClusterMembers).toHaveBeenCalledTimes(1);
  });

  it('fires retirement handlers only once per open target', async () => {
    vi.mocked(fetchClusterMembers).mockRejectedValue(notFound());
    const onClose = vi.fn();
    const onAnnounce = vi.fn();

    const { rerender } = renderHook(
      ({ id }: { id: string | null }) =>
        useLiveReviewTarget(id, { resolveSurvivor: () => null, onClose, onAnnounce }),
      { wrapper: createWrapper(), initialProps: { id: 'cluster-x' } },
    );

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    // Same id re-render must not re-fire.
    rerender({ id: 'cluster-x' });
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(onAnnounce).toHaveBeenCalledTimes(1);
    });
  });

  it('S5-02: record-after-404 rebinds (not permanent stale null from old memo)', async () => {
    // 404 first with empty survivor map → retired/close. Then record survivor and
    // re-render: lazy resolve must upgrade to rebound. Old useMemo deps
    // [retired, openClusterId] kept survivorId null forever after the first 404.
    vi.mocked(fetchClusterMembers).mockRejectedValue(notFound('cluster-x'));
    const survivors = new Map<string, string>();
    const onAnnounce = vi.fn();
    const onRebind = vi.fn();
    const onClose = vi.fn();

    const { result, rerender } = renderHook(
      () =>
        useLiveReviewTarget('cluster-x', {
          resolveSurvivor: (id) => survivors.get(id) ?? null,
          onAnnounce,
          onRebind,
          onClose,
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.status).toBe('retired');
    });
    expect(result.current.resolvedClusterId).toBeNull();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onRebind).not.toHaveBeenCalled();

    // Mutation success records survivor after the 404 (map mutates; same open id).
    survivors.set('cluster-x', 'cluster-survivor');
    rerender();

    await waitFor(() => {
      expect(result.current.status).toBe('rebound');
    });
    expect(result.current.resolvedClusterId).toBe('cluster-survivor');
    expect(onRebind).toHaveBeenCalledTimes(1);
    expect(onRebind).toHaveBeenCalledWith('cluster-survivor');
    expect(onAnnounce).toHaveBeenCalledWith(LIVE_TARGET_REBIND_ANNOUNCE);
  });
});
