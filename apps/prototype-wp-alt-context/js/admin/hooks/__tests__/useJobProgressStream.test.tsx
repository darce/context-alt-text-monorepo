import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { JOB_STATUS, useJobProgressStream } from '../useJobProgressStream';
import { useJobCoordination } from '../useJobCoordination';
import { resetConfigCache, setNonce } from '../../api/config';

vi.mock('../useJobCoordination', () => ({
  useJobCoordination: vi.fn(),
}));

class MockEventSource {
  static instances: MockEventSource[] = [];
  static CLOSED = 2;

  onerror: ((event: Event) => void) | null = null;
  readyState = 1;
  private listeners = new Map<string, Set<(event: MessageEvent) => void>>();

  constructor(readonly url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    const existing = this.listeners.get(type) ?? new Set();
    existing.add(listener);
    this.listeners.set(type, existing);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.readyState = MockEventSource.CLOSED;
  }

  emit(type: string, payload: unknown): void {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

describe('useJobProgressStream', () => {
  const useJobCoordinationMock = vi.mocked(useJobCoordination);

  beforeEach(() => {
    MockEventSource.instances = [];
    vi.useRealTimers();
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionJobs: 'http://localhost/recognition/jobs',
      },
    };
    resetConfigCache();
    useJobCoordinationMock.mockReturnValue({ isPrimary: true, channel: null });
    globalThis.EventSource = MockEventSource as unknown as typeof EventSource;
  });

  it('opens a single EventSource for progress updates', async () => {
    renderHook(() => useJobProgressStream('job-123'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0];

    act(() => {
      source.emit('progress', { completed: 1, total: 5, status: 'running' });
      source.emit('progress', { completed: 2, total: 5, status: 'running' });
      source.emit('progress', { completed: 3, total: 5, status: 'running' });
    });

    expect(MockEventSource.instances).toHaveLength(1);
  });

  it('stores phase and face metrics from progress events', async () => {
    const { result } = renderHook(() => useJobProgressStream('job-metrics'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0];

    act(() => {
      source.emit('progress', {
        completed: 2,
        total: 5,
        status: 'running',
        phase: 'detecting',
        images_processed: 2,
        faces_found: 8,
      });
    });

    await waitFor(() => {
      expect(result.current.progress).toEqual({
        completed: 2,
        total: 5,
        phase: 'detecting',
        images_processed: 2,
        faces_found: 8,
      });
    });
  });

  it('stores clustering metrics from progress events', async () => {
    const { result } = renderHook(() => useJobProgressStream('job-cluster'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0];

    act(() => {
      source.emit('progress', {
        completed: 1,
        total: 4,
        status: 'running',
        phase: 'clustering',
        clusters_created: 2,
      });
    });

    await waitFor(() => {
      expect(result.current.progress).toEqual({
        completed: 1,
        total: 4,
        phase: 'clustering',
        clusters_created: 2,
      });
    });
  });

  it('uses the latest progress when a job completes', async () => {
    const postMessage = vi.fn();
    useJobCoordinationMock.mockReturnValue({
      isPrimary: true,
      channel: { postMessage } as unknown as BroadcastChannel,
    });

    const { result } = renderHook(() => useJobProgressStream('job-456'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0];

    act(() => {
      source.emit('progress', { completed: 3, total: 10, status: 'running' });
    });

    await waitFor(() => {
      expect(result.current.progress).toEqual({ completed: 3, total: 10 });
    });

    act(() => {
      source.emit('done', { status: 'completed' });
    });

    await waitFor(() => {
      expect(result.current.progress).toEqual({ completed: 10, total: 10 });
      expect(result.current.status).toBe('completed');
    });

    expect(postMessage).toHaveBeenCalledWith({
      type: 'JOB_PROGRESS',
      payload: { progress: { completed: 10, total: 10 }, status: 'completed', etaSeconds: null },
    });
  });

  it('marks the stream stalled after silence and retry opens a new EventSource', async () => {
    vi.useFakeTimers();

    const { result } = renderHook(() => useJobProgressStream('job-stalled'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const firstSource = MockEventSource.instances[0];

    act(() => {
      vi.advanceTimersByTime(31_000);
    });

    await waitFor(() => {
      expect(result.current.stalledForSeconds).toBe(31);
    });

    act(() => {
      result.current.retry();
    });

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(2));
    expect(firstSource.readyState).toBe(MockEventSource.CLOSED);
    expect(result.current.stalledForSeconds).toBeNull();
  });

  it('rebuilds EventSource URL with live nonce after setNonce between reconnects [TEST-15]', async () => {
    const { result } = renderHook(() => useJobProgressStream('job-nonce'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const firstUrl = MockEventSource.instances[0].url;
    expect(firstUrl).toContain('_wpnonce=test-nonce');

    setNonce('fresh-nonce-99');
    act(() => {
      result.current.retry();
    });

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(2));
    const secondUrl = MockEventSource.instances[1].url;
    expect(secondUrl).toContain('_wpnonce=fresh-nonce-99');
    expect(secondUrl).not.toContain('_wpnonce=test-nonce');
  });

  it('clears the stalled state when progress resumes', async () => {
    vi.useFakeTimers();

    const { result } = renderHook(() => useJobProgressStream('job-recovered'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0];

    act(() => {
      vi.advanceTimersByTime(31_000);
    });

    await waitFor(() => {
      expect(result.current.stalledForSeconds).toBe(31);
    });

    act(() => {
      source.emit('progress', { completed: 1, total: 5, status: 'running' });
    });

    await waitFor(() => {
      expect(result.current.stalledForSeconds).toBeNull();
      expect(result.current.lastEventAt).not.toBeNull();
    });
  });

  it('120s of silence renders as stalled, not failed (FEBT1-W2D-01/W2D-02)', async () => {
    vi.useFakeTimers();

    const { result } = renderHook(() => useJobProgressStream('job-quiet-120s'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

    act(() => {
      vi.advanceTimersByTime(120_000);
    });

    await waitFor(() => {
      expect(result.current.status).toBe(JOB_STATUS.STALLED);
      expect(result.current.status).not.toBe(JOB_STATUS.FAILED);
      expect(result.current.stalledForSeconds).toBe(120);
    });
  });
});
