import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthExpiredError, HTTPError } from '../../utils/http';
import { DEFAULT_COOLDOWN_SECONDS } from '../../utils/recognitionCooldown';
import { RETRY_AFTER_MAX_MS } from '../../utils/retryAfter';
import { setLogLevel, setLogSink, type LogRecord } from '../../utils/logger';
import { buildStatusText } from '../jobStateMachineProgress';
import {
  CLUSTER_RETRY_MAX_ATTEMPTS,
  canAutoRetryCluster,
  createClusterAutoRetry,
  formatClusterQueuedStatus,
  formatClusterRetryExhaustedMessage,
  isRetryableClusterError,
  resolveClusterRetryDelaySeconds,
} from '../clusterAutoRetry';

const clusterError = (status: number, message: string, retryAfterSeconds?: number): HTTPError =>
  new HTTPError({
    status,
    retryAfterSeconds,
    endpoint: '/cluster',
    bodyPreview: '',
    message,
  });

const rateLimited = (retryAfterSeconds: number | undefined = 2): HTTPError =>
  clusterError(429, 'Request to /cluster failed (429): rate limited', retryAfterSeconds);

const rateLimitedNoRetryAfter = (): HTTPError => clusterError(429, 'Request to /cluster failed (429): rate limited');

const serverError = (): HTTPError => clusterError(500, 'Request to /cluster failed (500): boom');

const clientError = (): HTTPError => clusterError(400, 'Request to /cluster failed (400): bad');

const serviceUnavailable = (retryAfterSeconds?: number): HTTPError =>
  clusterError(503, 'Request to /cluster failed (503): unavailable', retryAfterSeconds);

describe('clusterAutoRetry pure helpers', () => {
  it('exports a hard ceiling of exactly 3 total attempts (RES-06)', () => {
    expect(CLUSTER_RETRY_MAX_ATTEMPTS).toBe(3);
  });

  it('treats 429 and 503-with-Retry-After as retryable via isCooldown (E-07)', () => {
    expect(isRetryableClusterError(rateLimited(2))).toBe(true);
    expect(isRetryableClusterError(serviceUnavailable(5))).toBe(true);
    expect(isRetryableClusterError(serviceUnavailable())).toBe(false);
    expect(isRetryableClusterError(serverError())).toBe(false);
    expect(isRetryableClusterError(clientError())).toBe(false);
    expect(isRetryableClusterError(new Error('plain'))).toBe(false);
  });

  it('retries a pre-classified AppError 429 without instanceof HTTPError (E-02)', () => {
    const classified = {
      _tag: 'http' as const,
      status: 429,
      endpoint: '/cluster',
      retryAfterMs: 4000,
      message: 'rate limited',
      cause: null,
    };
    expect(isRetryableClusterError(classified)).toBe(true);
    expect(resolveClusterRetryDelaySeconds(classified)).toBe(4);
    expect(canAutoRetryCluster(1, classified)).toBe(true);
  });

  it('503 with Retry-After uses classifyError retryAfterMs (E-07)', () => {
    expect(isRetryableClusterError(serviceUnavailable(5))).toBe(true);
    expect(resolveClusterRetryDelaySeconds(serviceUnavailable(5))).toBe(5);
    expect(canAutoRetryCluster(1, serviceUnavailable(5))).toBe(true);
    expect(canAutoRetryCluster(3, serviceUnavailable(5))).toBe(false);
  });

  it('AuthExpiredError falls through terminal (never auto-retried) [TEST-15]', () => {
    const authExpired = new AuthExpiredError({ endpoint: '/cluster', status: 403 });
    expect(isRetryableClusterError(authExpired)).toBe(false);
    expect(canAutoRetryCluster(1, authExpired)).toBe(false);
    expect(canAutoRetryCluster(0, authExpired)).toBe(false);
  });

  it('honors Retry-After and falls back to DEFAULT_COOLDOWN_SECONDS', () => {
    expect(resolveClusterRetryDelaySeconds(rateLimited(2))).toBe(2);
    expect(resolveClusterRetryDelaySeconds(rateLimitedNoRetryAfter())).toBe(DEFAULT_COOLDOWN_SECONDS);
  });

  it('clamps Retry-After: 3600 to the shared ceiling [E-01]', () => {
    expect(resolveClusterRetryDelaySeconds(rateLimited(3600))).toBe(RETRY_AFTER_MAX_MS / 1000);
  });

  it('clamps overflow-scale Retry-After below the 32-bit setTimeout bound [E-01]', () => {
    const seconds = resolveClusterRetryDelaySeconds(rateLimited(2_678_400));
    expect(seconds).toBe(RETRY_AFTER_MAX_MS / 1000);
    expect(seconds * 1000).toBeLessThan(2 ** 31 - 1);
  });

  it('falls back to DEFAULT_COOLDOWN_SECONDS for negative/NaN/Infinity Retry-After [E-01]', () => {
    expect(resolveClusterRetryDelaySeconds(rateLimited(Number.NaN))).toBe(DEFAULT_COOLDOWN_SECONDS);
    expect(resolveClusterRetryDelaySeconds(rateLimited(Number.POSITIVE_INFINITY))).toBe(
      DEFAULT_COOLDOWN_SECONDS,
    );
    expect(resolveClusterRetryDelaySeconds(rateLimited(-3))).toBe(DEFAULT_COOLDOWN_SECONDS);
  });

  it('allows auto-retry only while attempts remain under the ceiling', () => {
    expect(canAutoRetryCluster(1, rateLimited(2))).toBe(true);
    expect(canAutoRetryCluster(2, rateLimited(2))).toBe(true);
    expect(canAutoRetryCluster(3, rateLimited(2))).toBe(false);
    expect(canAutoRetryCluster(1, clientError())).toBe(false);
  });

  it('formats honest queued status copy (AGT-10)', () => {
    expect(formatClusterQueuedStatus(2)).toBe('Clustering queued — starting in 2s');
  });
});

describe('createClusterAutoRetry', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const buildHarness = () => {
    const mutate = vi.fn();
    const onQueued = vi.fn();
    const onExhausted = vi.fn();
    const onTerminalError = vi.fn();
    const controller = createClusterAutoRetry({
      mutate,
      onQueued,
      onExhausted,
      onTerminalError,
      fallbackErrorMessage: 'Clustering failed. Please try again.',
    });
    return { mutate, onQueued, onExhausted, onTerminalError, controller };
  };

  it('(a) 429 with Retry-After: 2 → exactly 3 bounded attempts spaced by the server delay', () => {
    const { mutate, onQueued, onExhausted, onTerminalError, controller } = buildHarness();

    controller.start();
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(controller.getAttemptCount()).toBe(1);

    expect(controller.noteError(rateLimited(2))).toBe(true);
    expect(onQueued).toHaveBeenLastCalledWith(2);
    expect(onTerminalError).not.toHaveBeenCalled();

    vi.advanceTimersByTime(2000);
    expect(mutate).toHaveBeenCalledTimes(2);
    expect(controller.getAttemptCount()).toBe(2);

    expect(controller.noteError(rateLimited(2))).toBe(true);
    vi.advanceTimersByTime(2000);
    expect(mutate).toHaveBeenCalledTimes(3);
    expect(controller.getAttemptCount()).toBe(3);

    expect(controller.noteError(rateLimited(2))).toBe(false);
    expect(mutate).toHaveBeenCalledTimes(3);
    expect(onExhausted).toHaveBeenCalledTimes(1);
    expect(onTerminalError).toHaveBeenCalledWith(formatClusterRetryExhaustedMessage());

    vi.advanceTimersByTime(10_000);
    expect(mutate).toHaveBeenCalledTimes(3);
  });

  it('(b) exposes queued-status copy between attempts with the right seconds', () => {
    const { onQueued, controller } = buildHarness();

    controller.start();
    controller.noteError(rateLimited(2));

    expect(onQueued).toHaveBeenCalledWith(2);
    const status = buildStatusText({
      clusterPending: false,
      clusterQueuedSeconds: 2,
      sseStatus: 'pending',
      sseProgress: null,
      activeJobIds: [],
      scanStatus: undefined,
      latestJobId: null,
      scanPending: false,
    });
    expect(status).toBe('Clustering queued — starting in 2s');

    vi.advanceTimersByTime(2000);
    expect(onQueued).toHaveBeenLastCalledWith(null);
  });

  it('(c) manual-retry affordance after ceiling resets attempts', () => {
    const { mutate, onExhausted, onTerminalError, controller } = buildHarness();

    controller.start();
    controller.noteError(rateLimited(1));
    vi.advanceTimersByTime(1000);
    controller.noteError(rateLimited(1));
    vi.advanceTimersByTime(1000);
    controller.noteError(rateLimited(1));

    expect(onExhausted).toHaveBeenCalledTimes(1);
    expect(onTerminalError).toHaveBeenCalledWith(formatClusterRetryExhaustedMessage());
    expect(mutate).toHaveBeenCalledTimes(3);

    controller.manualRetry();
    expect(mutate).toHaveBeenCalledTimes(4);
    expect(controller.getAttemptCount()).toBe(1);

    // Full auto-retry budget available again after manual retry.
    controller.noteError(rateLimited(1));
    vi.advanceTimersByTime(1000);
    expect(mutate).toHaveBeenCalledTimes(5);
  });

  it('(d) recovered 429 (attempt 2 succeeds) → completes with no error surface', () => {
    const { mutate, onQueued, onExhausted, onTerminalError, controller } = buildHarness();

    controller.start();
    expect(mutate).toHaveBeenCalledTimes(1);

    expect(controller.noteError(rateLimited(2))).toBe(true);
    expect(onQueued).toHaveBeenLastCalledWith(2);

    vi.advanceTimersByTime(2000);
    expect(mutate).toHaveBeenCalledTimes(2);

    controller.noteSuccess();
    expect(onQueued).toHaveBeenLastCalledWith(null);
    expect(onExhausted).not.toHaveBeenCalled();
    expect(onTerminalError).not.toHaveBeenCalled();
    expect(controller.getAttemptCount()).toBe(0);
  });

  it('503 with Retry-After auto-retries with the server delay (E-07)', () => {
    const { mutate, onQueued, onExhausted, onTerminalError, controller } = buildHarness();

    controller.start();
    expect(mutate).toHaveBeenCalledTimes(1);

    expect(controller.noteError(serviceUnavailable(2))).toBe(true);
    expect(onQueued).toHaveBeenLastCalledWith(2);
    expect(onTerminalError).not.toHaveBeenCalled();
    expect(onExhausted).not.toHaveBeenCalled();

    vi.advanceTimersByTime(2000);
    expect(mutate).toHaveBeenCalledTimes(2);
  });

  it('(e) non-429 error → immediate error path, zero retries', () => {
    const { mutate, onQueued, onExhausted, onTerminalError, controller } = buildHarness();

    controller.start();
    expect(mutate).toHaveBeenCalledTimes(1);

    expect(controller.noteError(clientError())).toBe(false);
    expect(onTerminalError).toHaveBeenCalledWith('Request to /cluster failed (400): bad');
    expect(onExhausted).not.toHaveBeenCalled();
    expect(onQueued).toHaveBeenCalledWith(null);

    vi.advanceTimersByTime(60_000);
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it('AuthExpiredError → terminal path, zero retries (UXP-NET-2 pin)', () => {
    const { mutate, onExhausted, onTerminalError, controller } = buildHarness();
    const authExpired = new AuthExpiredError({
      endpoint: '/cluster',
      status: 403,
      message: 'Authentication expired for /cluster (403).',
    });

    controller.start();
    expect(controller.noteError(authExpired)).toBe(false);
    expect(onTerminalError).toHaveBeenCalledWith(authExpired.message);
    expect(onExhausted).not.toHaveBeenCalled();

    vi.advanceTimersByTime(60_000);
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it('uses DEFAULT_COOLDOWN_SECONDS when Retry-After is null', () => {
    const { mutate, onQueued, controller } = buildHarness();

    controller.start();
    controller.noteError(rateLimitedNoRetryAfter());
    expect(onQueued).toHaveBeenLastCalledWith(DEFAULT_COOLDOWN_SECONDS);

    vi.advanceTimersByTime((DEFAULT_COOLDOWN_SECONDS - 1) * 1000);
    expect(mutate).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(1000);
    expect(mutate).toHaveBeenCalledTimes(2);
  });
  it('dispose latches: a late 429 after unmount schedules no zombie retry', () => {
    const { mutate, controller } = buildHarness();

    controller.start();
    expect(mutate).toHaveBeenCalledTimes(1);

    controller.dispose();

    // 429 lands after unmount (mutation callbacks still fire post-unmount in RQ v5).
    const scheduled = controller.noteError(rateLimited(2));
    expect(scheduled).toBe(false);

    vi.advanceTimersByTime(60_000);
    expect(mutate).toHaveBeenCalledTimes(1);

    // Latched for good: start/manualRetry are no-ops too.
    controller.start();
    controller.manualRetry();
    expect(mutate).toHaveBeenCalledTimes(1);
  });
});

describe('cluster auto-retry observability [FEBT1-W2B-03]', () => {
  let records: LogRecord[] = [];

  beforeEach(() => {
    records = [];
    setLogLevel('debug');
    setLogSink((record) => {
      records.push(record);
    });
  });

  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
  });

  const listener = () => ({
    mutate: vi.fn(),
    onQueued: vi.fn(),
    onExhausted: vi.fn(),
    onTerminalError: vi.fn(),
    fallbackErrorMessage: 'fallback',
  });

  it('emits one structured line per scheduled auto-retry', () => {
    vi.useFakeTimers();
    try {
      const controller = createClusterAutoRetry(listener());
      controller.start();
      controller.noteError(clusterError(429, 'slow down', 5));

      const scheduled = records.filter((record) => record.message === 'cluster.retry_scheduled');
      expect(scheduled).toHaveLength(1);
      expect(scheduled[0].level).toBe('info');
      expect(scheduled[0].fields).toEqual(
        expect.objectContaining({ attempt: 1, maxAttempts: CLUSTER_RETRY_MAX_ATTEMPTS, status: 429, tag: 'http' }),
      );
      expect(scheduled[0].fields.delayMs as number).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('distinguishes an exhausted ceiling from a declined non-cooldown error', () => {
    vi.useFakeTimers();
    try {
      const controller = createClusterAutoRetry(listener());
      controller.start();
      for (let i = 0; i < CLUSTER_RETRY_MAX_ATTEMPTS; i += 1) {
        controller.noteError(clusterError(429, 'slow down', 1));
        vi.advanceTimersByTime(2_000);
      }
      expect(records.filter((record) => record.message === 'cluster.retry_exhausted')).toHaveLength(1);

      records.length = 0;
      const declined = createClusterAutoRetry(listener());
      declined.start();
      declined.noteError(clusterError(400, 'bad request'));
      const lines = records.filter((record) => record.message === 'cluster.retry_declined');
      expect(lines).toHaveLength(1);
      expect(lines[0].fields).toEqual(expect.objectContaining({ status: 400, attempt: 1 }));
      expect(records.some((record) => record.message === 'cluster.retry_scheduled')).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});
