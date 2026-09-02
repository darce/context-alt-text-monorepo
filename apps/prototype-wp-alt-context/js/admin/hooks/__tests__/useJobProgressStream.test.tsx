import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { JOB_EVENT, type JobEvent } from '../jobMachine';
import { JOB_STATUS, useJobProgressStream } from '../useJobProgressStream';
import { useJobCoordination } from '../useJobCoordination';
import { resetConfigCache, setNonce } from '../../api/config';

const jobReducerSpy = vi.hoisted(() => vi.fn());
const logJobEventSpy = vi.hoisted(() => vi.fn());

vi.mock('../useJobCoordination', () => ({
  useJobCoordination: vi.fn(),
}));

vi.mock('../jobMachine', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../jobMachine')>();
  jobReducerSpy.mockImplementation(actual.jobReducer);
  return { ...actual, jobReducer: jobReducerSpy };
});

vi.mock('../../utils/logger', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../utils/logger')>();
  logJobEventSpy.mockImplementation(actual.logJobEvent);
  return { ...actual, logJobEvent: logJobEventSpy };
});

const dispatchedEvents = (): JobEvent[] => jobReducerSpy.mock.calls.map(([, event]) => event as JobEvent);

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
    jobReducerSpy.mockClear();
    logJobEventSpy.mockClear();
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

  it('omits failedCount on completed_with_errors when the wire carries none (FEBT1-W2D-05)', async () => {
    const { result } = renderHook(() => useJobProgressStream('job-cwe'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0];

    act(() => {
      source.emit('done', { status: 'completed_with_errors', completed: 4, total: 5 });
    });

    await waitFor(() => {
      expect(result.current.status).toBe(JOB_STATUS.COMPLETED_WITH_ERRORS);
    });

    const evt = dispatchedEvents().find((event) => event.type === JOB_EVENT.COMPLETE_WITH_ERRORS);
    expect(evt).toBeDefined();
    expect('failedCount' in (evt ?? {})).toBe(false);
  });

  it('FAIL uses the parsed server error message, not the literal stream failed (FEBT1-W2C-02)', async () => {
    const { result } = renderHook(() => useJobProgressStream('job-proj-unavail'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0];

    act(() => {
      source.emit('error', { message: 'projection backend unavailable' });
    });

    await waitFor(() => {
      expect(result.current.status).toBe(JOB_STATUS.FAILED);
    });

    const evt = dispatchedEvents().find((event) => event.type === JOB_EVENT.FAIL);
    expect(evt).toBeDefined();
    if (evt?.type !== JOB_EVENT.FAIL) {
      throw new Error('expected FAIL event');
    }
    expect(evt.error.message).toBe('projection backend unavailable');
    expect(evt.error.message).not.toContain('stream failed');
  });

  it('FAILED terminal log record omits failedCount rather than deriving it (FEBT1-W2D-05)', async () => {
    renderHook(() => useJobProgressStream('job-fail-log'));

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    const source = MockEventSource.instances[0];

    act(() => {
      source.emit('error', { message: 'projection backend unavailable' });
    });

    await waitFor(() => {
      expect(logJobEventSpy.mock.calls.some((call) => call[1] === 'stream.done')).toBe(true);
    });

    const doneLog = logJobEventSpy.mock.calls.find((call) => call[1] === 'stream.done');
    expect(doneLog).toBeDefined();
    const fields = doneLog?.[2] as Record<string, unknown> | undefined;
    expect(fields).toBeDefined();
    expect('failedCount' in (fields ?? {})).toBe(false);
  });
});
