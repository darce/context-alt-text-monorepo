import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { JOB_STATUS as MACHINE_JOB_STATUS } from '../jobMachine';
import { JOB_STATUS, useJobProgressStream } from '../useJobProgressStream';
import { useJobCoordination } from '../useJobCoordination';
import { resetConfigCache, setNonce } from '../../api/config';
import { setLogLevel, setLogSink, type LogRecord } from '../../utils/logger';

vi.mock('../useJobCoordination', () => ({
  useJobCoordination: vi.fn(),
}));

class MockEventSource {
  static instances: MockEventSource[] = [];
  static CLOSED = 2;
  static CONNECTING = 0;
  static OPEN = 1;

  onerror: ((event: Event) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;
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

  emitRaw(type: string, data: string): void {
    const event = new MessageEvent(type, { data });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
}

const captureRecords = (): LogRecord[] => {
  const records: LogRecord[] = [];
  setLogSink((record) => {
    records.push(record);
  });
  return records;
};

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
    setLogLevel('debug');
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

  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
  });

  describe('terminal-status handling [FEBT1G-H-03]', () => {
    it('does not report an unrecognised done status as completed', async () => {
      const records = captureRecords();
      const { result } = renderHook(() => useJobProgressStream('job-unknown-status'));

      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emit('done', { status: 'schema_evolved_status' });
      });

      await waitFor(() => expect(result.current.status).toBe(JOB_STATUS.FAILED));
      expect(records.some((record) => record.message === 'sse.done_unknown_status')).toBe(true);
      expect(records.some((record) => record.fields.status === JOB_STATUS.COMPLETED)).toBe(false);
    });

    it('does not report a missing done status as completed', async () => {
      const { result } = renderHook(() => useJobProgressStream('job-missing-status'));

      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emit('done', { completed: 3, total: 3 });
      });

      await waitFor(() => expect(result.current.status).toBe(JOB_STATUS.FAILED));
    });

    it("reports the producer's 'rejected' terminal status as failed, not completed", async () => {
      const { result } = renderHook(() => useJobProgressStream('job-rejected'));

      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emit('done', { status: 'rejected', completed: 1, total: 4 });
      });

      await waitFor(() => expect(result.current.status).toBe(JOB_STATUS.REJECTED));
    });

    it('treats an unparseable terminal frame as a failure rather than a silent no-op', async () => {
      const { result } = renderHook(() => useJobProgressStream('job-bad-done'));

      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emitRaw('done', '{not json');
      });

      await waitFor(() => expect(result.current.status).toBe(JOB_STATUS.FAILED));
    });

    it('does not invent a failedCount on the completed_with_errors log record', async () => {
      const records = captureRecords();
      renderHook(() => useJobProgressStream('job-partial'));

      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emit('done', {
          status: 'completed_with_errors',
          completed: 8,
          total: 10,
        });
      });

      const done = await waitFor(() => {
        const record = records.find((entry) => entry.fields.event === 'stream.done');
        expect(record).toBeDefined();
        return record as LogRecord;
      });
      expect(done.fields.status).toBe('completed_with_errors');
      expect(done.fields).not.toHaveProperty('failedCount');
    });
  });

  describe('observer tabs honour the broadcast status [FEBT1G-H-02]', () => {
    const renderObserver = (status: string) => {
      const listeners = new Set<(event: MessageEvent) => void>();
      const channel = {
        addEventListener: (_type: string, listener: (event: MessageEvent) => void) => {
          listeners.add(listener);
        },
        removeEventListener: (_type: string, listener: (event: MessageEvent) => void) => {
          listeners.delete(listener);
        },
        postMessage: vi.fn(),
      } as unknown as BroadcastChannel;

      useJobCoordinationMock.mockReturnValue({ isPrimary: false, channel });
      const rendered = renderHook(() => useJobProgressStream('job-observer'));

      act(() => {
        const event = {
          data: {
            type: 'JOB_PROGRESS',
            payload: { progress: { completed: 4, total: 4 }, status, etaSeconds: null },
          },
        } as MessageEvent;
        listeners.forEach((listener) => listener(event));
      });
      return rendered;
    };

    it.each([JOB_STATUS.COMPLETED, JOB_STATUS.COMPLETED_WITH_ERRORS, JOB_STATUS.FAILED])(
      'surfaces a broadcast %s instead of forcing running',
      async (status) => {
        const { result } = renderObserver(status);
        await waitFor(() => expect(result.current.status).toBe(status));
      },
    );

    it('ignores a broadcast with an unrecognised status', async () => {
      const records = captureRecords();
      const { result } = renderObserver('not_a_status');
      await waitFor(() => {
        expect(records.some((record) => record.message === 'sse.broadcast_unknown_status')).toBe(true);
      });
      expect(result.current.status).toBe(JOB_STATUS.PENDING);
    });
  });

  describe('quiet stream observability [FEBT1-W2B-04][FEBT1-W2B-05]', () => {
    it('emits one wide sse.stalled event carrying the quiet window', async () => {
      vi.useFakeTimers();
      const records = captureRecords();

      renderHook(() => useJobProgressStream('job-quiet'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

      act(() => {
        vi.advanceTimersByTime(31_000);
      });

      const stalled = await waitFor(() => {
        const found = records.filter((record) => record.message === 'sse.stalled');
        expect(found).toHaveLength(1);
        return found[0];
      });
      expect(stalled.level).toBe('warn');
      expect(stalled.fields.jobId).toBe('job-quiet');
      expect(stalled.fields.reconnectAttempts).toBe(0);
      expect(stalled.fields.quietMs as number).toBeGreaterThanOrEqual(30_000);
      vi.useRealTimers();
    });

    it('[FEBT1-W2D-02] a long quiet stream never becomes terminal on its own', async () => {
      vi.useFakeTimers();
      const { result } = renderHook(() => useJobProgressStream('job-long-quiet'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

      // Ten minutes of silence on an OPEN stream: a describe run waiting on GPU warmup.
      act(() => {
        vi.advanceTimersByTime(600_000);
      });

      expect(result.current.status).not.toBe(JOB_STATUS.FAILED);
      expect(result.current.stalledForSeconds ?? 0).toBeGreaterThanOrEqual(600);
      vi.useRealTimers();
    });

    it('logs a malformed progress frame at warn, not error, and keeps the stream open', async () => {
      const records = captureRecords();
      const { result } = renderHook(() => useJobProgressStream('job-malformed'));

      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emitRaw('progress', '{not json');
        MockEventSource.instances[0].emit('progress', { completed: 'x', total: 5, status: 'running' });
      });

      const parseFailures = records.filter((record) => record.message === 'sse.progress_parse_failed');
      expect(parseFailures).toHaveLength(2);
      parseFailures.forEach((record) => expect(record.level).toBe('warn'));

      act(() => {
        MockEventSource.instances[0].emit('progress', { completed: 2, total: 5, status: 'running' });
      });
      await waitFor(() => expect(result.current.progress).toEqual({ completed: 2, total: 5 }));
    });
  });

  describe('reconnect accounting is wired to real transport events [FEBT1-W2D-03]', () => {
    it('a manual retry followed by a re-open leaves the job running, not failed', async () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useJobProgressStream('job-reconnect'));
        await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

        act(() => {
          vi.advanceTimersByTime(31_000);
        });
        await waitFor(() => expect(result.current.stalledForSeconds).toBe(31));

        act(() => {
          result.current.retry();
        });
        await waitFor(() => expect(MockEventSource.instances).toHaveLength(2));
        expect(result.current.stalledForSeconds).toBeNull();
        expect(result.current.status).not.toBe(JOB_STATUS.FAILED);
      } finally {
        vi.useRealTimers();
      }
    });

    it('the browser re-establishing the transport does not count against the ceiling forever', async () => {
      vi.useFakeTimers();
      try {
        const records = captureRecords();
        const { result } = renderHook(() => useJobProgressStream('job-browser-reconnect'));
        await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
        const source = MockEventSource.instances[0];

        // The onopen/onerror handlers exist so the machine can observe real reconnects at all
        // — before this fix RECONNECTED had no production dispatch site.
        expect(source.onopen).toBeInstanceOf(Function);
        expect(source.onerror).toBeInstanceOf(Function);

        act(() => {
          source.onopen?.(new Event('open'));
          for (let attempt = 0; attempt < 10; attempt += 1) {
            source.readyState = MockEventSource.CONNECTING;
            source.onerror?.(new Event('error'));
            source.readyState = MockEventSource.OPEN;
            source.onopen?.(new Event('open'));
          }
        });

        // Every failed attempt was answered by a successful re-open, so the breaker stays closed.
        expect(result.current.status).not.toBe(JOB_STATUS.FAILED);

        // Observable proof that RECONNECTED actually reached the machine: after ten
        // attempt/re-open pairs the quiet-stream report still shows a reset counter. Without a
        // production RECONNECTED dispatch the ten RECONNECTING events would blow the ceiling
        // and the machine would be failed rather than stalled, so no sse.stalled line exists.
        act(() => {
          vi.advanceTimersByTime(31_000);
        });
        await waitFor(() => expect(result.current.stalledForSeconds).toBe(31));
        const stalled = records.filter((record) => record.message === 'sse.stalled');
        expect(stalled).toHaveLength(1);
        expect(stalled[0].fields.reconnectAttempts).toBe(0);
      } finally {
        vi.useRealTimers();
      }
    });
  });
  describe('one unified status vocabulary [FEBT1-LA-05]', () => {
    it('re-exports the machine\'s status map rather than owning a second one', () => {
      // The hook used to declare its own 7-member JOB_STATUS while jobMachine declared a
      // disjoint 8-member one. Identity — not deep equality — is the only assertion that
      // catches a re-introduced second copy (REF-26).
      expect(JOB_STATUS).toBe(MACHINE_JOB_STATUS);
    });

    it('projects the transport-only `stalled` state back to running, never leaking it as a status', async () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useJobProgressStream('job-projection'));
        await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
        act(() => {
          MockEventSource.instances[0].emit('progress', { completed: 1, total: 5, status: 'running' });
        });
        act(() => {
          vi.advanceTimersByTime(31_000);
        });

        // Quiet time is reported on its own channel; the lifecycle status stays `running`
        // so out-of-hook consumers (isScanRunning, buildStatusText) keep working (RLSE-04).
        expect(result.current.stalledForSeconds).toBeGreaterThanOrEqual(30);
        expect(result.current.status).toBe(JOB_STATUS.RUNNING);
      } finally {
        vi.useRealTimers();
      }
    });

    it('adopts the producer clustering status verbatim instead of flattening it to running', async () => {
      const { result } = renderHook(() => useJobProgressStream('job-clustering'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emit('progress', { completed: 1, total: 5, status: 'clustering' });
      });
      await waitFor(() => expect(result.current.status).toBe(JOB_STATUS.CLUSTERING));
    });

    it('does not promote pending to running just because the transport opened', async () => {
      const { result } = renderHook(() => useJobProgressStream('job-transport-only'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      // STREAM_OPEN fired on mount. Only the producer may claim `running` (rg-015).
      expect(result.current.status).toBe(JOB_STATUS.PENDING);
    });

    it('ignores a progress frame carrying a terminal status instead of treating it as live', async () => {
      const records = captureRecords();
      const { result } = renderHook(() => useJobProgressStream('job-bad-progress-status'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emit('progress', { completed: 1, total: 5, status: 'not_a_status' });
      });
      await waitFor(() =>
        expect(records.some((record) => record.message === 'sse.progress_unknown_status')).toBe(true),
      );
      expect(result.current.status).toBe(JOB_STATUS.PENDING);
    });
  });

  describe('failed counts reach the machine [FEBT1-LA-03]', () => {
    it('carries items_failed from the done frame onto the stream.done record', async () => {
      const records = captureRecords();
      renderHook(() => useJobProgressStream('job-failed-count'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emit('done', {
          status: 'completed_with_errors',
          completed: 8,
          total: 10,
          items_failed: 2,
        });
      });

      const done = await waitFor(() => {
        const record = records.find((entry) => entry.fields.event === 'stream.done');
        expect(record).toBeDefined();
        return record as LogRecord;
      });
      expect(done.fields.failedCount).toBe(2);
    });
  });

  describe('parse failures are discriminated [FEBT1-LA-04]', () => {
    it('reports json vs schema so a corrupt frame is distinguishable from contract drift', async () => {
      const records = captureRecords();
      renderHook(() => useJobProgressStream('job-parse-reason'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emitRaw('progress', '{not json');
        MockEventSource.instances[0].emit('progress', { completed: 'x', total: 5, status: 'running' });
      });

      const reasons = records
        .filter((record) => record.message === 'sse.progress_parse_failed')
        .map((record) => record.fields.reason);
      expect(reasons).toEqual(['json', 'schema']);
    });
  });

  describe('the SSE unit of work is observable [FEBT-1-W1-O-02]', () => {
    it('emits one correlated stream.open event per connection', async () => {
      const records = captureRecords();
      renderHook(() => useJobProgressStream('job-observable'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

      // Mutant 21 survived an earlier round because this filter keyed only on the `event`
      // field: renaming the record or downgrading its level left it green. Pin all three.
      const opens = records.filter((record) => record.message === 'stream.open');
      expect(opens).toHaveLength(1);
      expect(opens[0].level).toBe('info');
      expect(opens[0].fields.event).toBe('stream.open');
      expect(opens[0].fields.jobId).toBe('job-observable');
      expect(opens[0].fields.requestId).toBeTypeOf('string');
      expect(opens[0].fields.reconnectAttempts).toBe(0);
    });

    it('never writes the stream nonce or a raw id segment into the log', async () => {
      const records = captureRecords();
      setNonce('super-secret-nonce');
      renderHook(() => useJobProgressStream('7f3c1e2a-0000-4000-8000-000000000001'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

      const open = records.find((record) => record.message === 'stream.open');
      expect(open).toBeDefined();
      const endpoint = (open as LogRecord).fields.endpoint as string;
      expect(endpoint).not.toContain('super-secret-nonce');
      expect(endpoint).not.toContain('7f3c1e2a');
      expect(endpoint).toContain('<redacted>');
    });

    it('correlates stream.open and stream.done for one job under a single requestId', async () => {
      const records = captureRecords();
      renderHook(() => useJobProgressStream('job-correlated'));
      await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
      act(() => {
        MockEventSource.instances[0].emit('done', { status: 'completed', completed: 4, total: 4 });
      });

      const open = await waitFor(() => {
        const found = records.find((record) => record.message === 'stream.open');
        expect(found).toBeDefined();
        return found as LogRecord;
      });
      const done = await waitFor(() => {
        const found = records.find((record) => record.fields.event === 'stream.done');
        expect(found).toBeDefined();
        return found as LogRecord;
      });
      expect(open.fields.requestId).toBeTypeOf('string');
      expect(done.fields.requestId).toBe(open.fields.requestId);
      expect(done.fields.durationMs).toBeTypeOf('number');
      expect(done.fields.reconnectAttempts).toBe(0);
    });
  });
});
