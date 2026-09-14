import { describe, expect, it } from 'vitest';

import {
  measureRecordedReplay,
  measureTrueInference,
} from '../../../scripts/guided-browser-timing-harness.mjs';

type FrameCallback = () => void;

class FakeRuntime {
  private currentTime = 0;
  private nextHandle = 1;
  private readonly timers = new Map<number, { callback: () => void; dueAt: number }>();
  private readonly frames = new Map<number, FrameCallback>();

  get nowMs(): number {
    return this.currentTime;
  }

  readonly now = (): number => this.currentTime;

  readonly setTimer = (callback: () => void, delayMs: number): number => {
    const handle = this.nextHandle;
    this.nextHandle += 1;
    this.timers.set(handle, {
      callback,
      dueAt: this.currentTime + Math.max(0, delayMs),
    });
    return handle;
  };

  readonly clearTimer = (handle: number): void => {
    this.timers.delete(handle);
  };

  readonly requestAnimationFrame = (callback: FrameCallback): number => {
    const handle = this.nextHandle;
    this.nextHandle += 1;
    this.frames.set(handle, callback);
    return handle;
  };

  readonly cancelAnimationFrame = (handle: number): void => {
    this.frames.delete(handle);
  };

  advanceTo(nextTime: number): void {
    if (nextTime < this.currentTime) {
      throw new Error('fake clock cannot move backwards');
    }
    this.currentTime = nextTime;
  }

  runDueTimers(): void {
    while (true) {
      const next = [...this.timers.entries()]
        .filter(([, timer]) => timer.dueAt <= this.currentTime)
        .sort(([leftHandle, leftTimer], [rightHandle, rightTimer]) =>
          leftTimer.dueAt - rightTimer.dueAt || leftHandle - rightHandle,
        )[0];
      if (!next) {
        return;
      }
      this.timers.delete(next[0]);
      next[1].callback();
    }
  }

  flushFrames(): void {
    const callbacks = [...this.frames.values()];
    this.frames.clear();
    for (const callback of callbacks) {
      callback();
    }
  }
}

const flushMicrotasks = async (): Promise<void> => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};

const deferredOperation = (): { promise: Promise<void>; resolve: () => void } => {
  let resolvePromise: (() => void) | undefined;
  const promise = new Promise<void>((resolve) => {
    resolvePromise = () => resolve(undefined);
  });
  return {
    promise,
    resolve: () => resolvePromise?.(),
  };
};

describe('guided browser timing harness deadlines', () => {
  it('bounds request and render to one max_wait_ms window for true inference', async () => {
    const runtime = new FakeRuntime();
    const resultPromise = measureTrueInference({
      sendRequest: () =>
        new Promise<void>((resolve) => {
          runtime.setTimer(() => resolve(undefined), 90);
        }),
      readRenderedText: () => (runtime.nowMs >= 180 ? 'ready text' : ''),
      isTextReady: (text) => text === 'ready text',
      maxWaitMs: 100,
      now: runtime.now,
      requestAnimationFrame: runtime.requestAnimationFrame,
      cancelAnimationFrame: runtime.cancelAnimationFrame,
      setTimer: runtime.setTimer,
      clearTimer: runtime.clearTimer,
    });

    runtime.advanceTo(90);
    runtime.runDueTimers();
    await flushMicrotasks();

    runtime.advanceTo(180);
    runtime.runDueTimers();
    runtime.flushFrames();
    const result = await resultPromise;

    expect(result.status).toBe('render_timeout');
    expect(result.elapsed_request_to_render_ms).toBeNull();
    expect(result.elapsed_response_to_render_ms).toBeNull();
  });

  it('does not accept text observed by a frame after the deadline', async () => {
    const runtime = new FakeRuntime();
    let ready = false;
    const resultPromise = measureTrueInference({
      sendRequest: () => Promise.resolve(),
      readRenderedText: () => (ready ? 'ready text' : ''),
      isTextReady: (text) => text === 'ready text',
      maxWaitMs: 100,
      now: runtime.now,
      requestAnimationFrame: runtime.requestAnimationFrame,
      cancelAnimationFrame: runtime.cancelAnimationFrame,
      setTimer: runtime.setTimer,
      clearTimer: runtime.clearTimer,
    });

    await flushMicrotasks();
    runtime.advanceTo(101);
    ready = true;
    runtime.flushFrames();
    const result = await resultPromise;

    expect(result.status).toBe('render_timeout');
    expect(result.rendered_text).toBeNull();
  });

  it('treats a request promise resolved after the deadline as request_timeout', async () => {
    const runtime = new FakeRuntime();
    const operation = deferredOperation();
    const resultPromise = measureTrueInference({
      sendRequest: () => operation.promise,
      readRenderedText: () => 'ready text',
      isTextReady: (text) => text === 'ready text',
      maxWaitMs: 100,
      now: runtime.now,
      requestAnimationFrame: runtime.requestAnimationFrame,
      cancelAnimationFrame: runtime.cancelAnimationFrame,
      setTimer: runtime.setTimer,
      clearTimer: runtime.clearTimer,
    });

    runtime.advanceTo(101);
    operation.resolve();
    await flushMicrotasks();
    runtime.flushFrames();
    const result = await resultPromise;

    expect(result.status).toBe('request_timeout');
    expect(result.response_received_at_ms).toBeNull();
  });

  it('records a happy-path render inside the shared window', async () => {
    const runtime = new FakeRuntime();
    const operation = deferredOperation();
    const resultPromise = measureTrueInference({
      sendRequest: () => operation.promise,
      readRenderedText: () => (runtime.nowMs >= 50 ? 'ready text' : ''),
      isTextReady: (text) => text === 'ready text',
      maxWaitMs: 100,
      now: runtime.now,
      requestAnimationFrame: runtime.requestAnimationFrame,
      cancelAnimationFrame: runtime.cancelAnimationFrame,
      setTimer: runtime.setTimer,
      clearTimer: runtime.clearTimer,
    });

    runtime.advanceTo(20);
    operation.resolve();
    await flushMicrotasks();
    runtime.advanceTo(50);
    runtime.flushFrames();
    const result = await resultPromise;

    expect(result.status).toBe('rendered');
    expect(result.elapsed_request_to_render_ms).toBe(50);
    expect(result.elapsed_request_to_render_ms).toBeLessThanOrEqual(100);
    expect(result.rendered_text).toBe('ready text');
  });

  it('bounds recorded replay request and render to one max_wait_ms window', async () => {
    const runtime = new FakeRuntime();
    const resultPromise = measureRecordedReplay({
      triggerReplay: () =>
        new Promise<void>((resolve) => {
          runtime.setTimer(() => resolve(undefined), 90);
        }),
      readRenderedText: () => (runtime.nowMs >= 180 ? 'ready text' : ''),
      isTextReady: (text) => text === 'ready text',
      maxWaitMs: 100,
      now: runtime.now,
      requestAnimationFrame: runtime.requestAnimationFrame,
      cancelAnimationFrame: runtime.cancelAnimationFrame,
      setTimer: runtime.setTimer,
      clearTimer: runtime.clearTimer,
    });

    runtime.advanceTo(90);
    runtime.runDueTimers();
    await flushMicrotasks();

    runtime.advanceTo(180);
    runtime.runDueTimers();
    runtime.flushFrames();
    const result = await resultPromise;

    expect(result.status).toBe('render_timeout');
    expect(result.elapsed_replay_to_render_ms).toBeNull();
  });
});
