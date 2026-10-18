/**
 * Browser-side operator timing helpers for the guided demo.
 *
 * This module intentionally has no app/API imports and does not call fetch. The
 * operator supplies callbacks that trigger either a real inference request or a
 * recorded replay transition. The two modes have different result fields so a
 * replay cannot be reported as inference evidence.
 *
 * In a browser/Playwright page, call for example:
 *
 *   await measureTrueInference({
 *     sendRequest: () => operatorStartsTheAlready-configuredRequest(),
 *     readRenderedText: () => document.querySelector('#draft')?.textContent ?? '',
 *   });
 *
 * ``sendRequest`` must resolve after the UI has received the response and queued
 * its state update. The helper then waits for a requestAnimationFrame in which
 * the target text is actually observable. Clear stale text or provide
 * ``isTextReady`` that identifies the expected new text before measuring.
 */

export const GUIDED_BROWSER_TIMING_SCHEMA = 'altcontext-guided-browser-timing/v1';
export const DEFAULT_RENDER_TIMEOUT_MS = 180_000;

const defaultClock = () => performance.now();
const defaultRequestAnimationFrame = (callback) => requestAnimationFrame(callback);
const defaultCancelAnimationFrame = (handle) => cancelAnimationFrame(handle);

const defaultTextReady = (text) => text.trim().length > 0;

const errorText = (error) => (error instanceof Error ? `${error.name}: ${error.message}` : String(error));

const elapsed = (start, end) => (start === null || end === null ? null : Math.max(0, end - start));

/**
 * Wait until a non-stale text reader returns ready text during an animation
 * frame. All timestamps come from the injected/same ``performance.now`` clock.
 */
export const waitForRenderedText = async ({
  readRenderedText,
  isTextReady = defaultTextReady,
  maxWaitMs,
  deadlineMs,
  now = defaultClock,
  requestAnimationFrame = defaultRequestAnimationFrame,
  cancelAnimationFrame = defaultCancelAnimationFrame,
  setTimer = (callback, delayMs) => setTimeout(callback, delayMs),
  clearTimer = (handle) => clearTimeout(handle),
}) => {
  if (maxWaitMs !== undefined && (!Number.isFinite(maxWaitMs) || maxWaitMs <= 0)) {
    throw new Error('maxWaitMs must be a finite number greater than zero');
  }
  if (deadlineMs !== undefined && !Number.isFinite(deadlineMs)) {
    throw new Error('deadlineMs must be a finite number');
  }
  const effectiveMaxWaitMs = maxWaitMs ?? DEFAULT_RENDER_TIMEOUT_MS;
  const deadline = deadlineMs ?? now() + effectiveMaxWaitMs;

  return new Promise((resolve) => {
    let frameHandle = null;
    let timerHandle = null;
    let settled = false;

    const cleanup = () => {
      if (frameHandle !== null) {
        cancelAnimationFrame(frameHandle);
      }
      if (timerHandle !== null) {
        clearTimer(timerHandle);
      }
    };

    const finish = (result) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve(result);
    };

    const inspect = () => {
      if (settled) {
        return;
      }
      if (now() >= deadline) {
        finish({ ok: false, text: null, renderedAtMs: null, timedOut: true });
        return;
      }
      let text;
      try {
        text = String(readRenderedText() ?? '');
      } catch (error) {
        if (now() >= deadline) {
          finish({ ok: false, text: null, renderedAtMs: null, timedOut: true });
          return;
        }
        finish({ ok: false, text: null, renderedAtMs: null, error: errorText(error) });
        return;
      }
      const observedAt = now();
      if (observedAt >= deadline) {
        finish({ ok: false, text: null, renderedAtMs: null, timedOut: true });
        return;
      }
      const ready = isTextReady(text);
      const completedAt = now();
      if (completedAt >= deadline) {
        finish({ ok: false, text: null, renderedAtMs: null, timedOut: true });
        return;
      }
      if (ready) {
        finish({ ok: true, text, renderedAtMs: completedAt });
        return;
      }
      frameHandle = requestAnimationFrame(inspect);
    };

    const finishAtDeadline = () => {
      if (settled) {
        return;
      }
      const remainingMs = deadline - now();
      if (remainingMs <= 0) {
        finish({ ok: false, text: null, renderedAtMs: null, timedOut: true });
        return;
      }
      timerHandle = setTimer(finishAtDeadline, remainingMs);
    };
    const remainingMs = deadline - now();
    if (remainingMs <= 0) {
      finish({ ok: false, text: null, renderedAtMs: null, timedOut: true });
      return;
    }
    timerHandle = setTimer(finishAtDeadline, remainingMs);
    frameHandle = requestAnimationFrame(inspect);
  });
};

const awaitWithinDeadline = async ({ operation, maxWaitMs, deadlineMs, now, setTimer, clearTimer }) => {
  const deadline = deadlineMs ?? now() + maxWaitMs;
  return new Promise((resolve) => {
    let timerHandle = null;
    let settled = false;

    const cleanup = () => {
      if (timerHandle !== null) {
        clearTimer(timerHandle);
      }
    };
    const finish = (result) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve(result);
    };
    const finishAtDeadline = () => {
      if (settled) {
        return;
      }
      const remainingMs = deadline - now();
      if (remainingMs <= 0) {
        finish({ ok: false, timedOut: true, error: `operation exceeded ${maxWaitMs}ms` });
        return;
      }
      timerHandle = setTimer(finishAtDeadline, remainingMs);
    };

    const finishOperationFailure = (error) => {
      if (now() >= deadline) {
        finish({ ok: false, timedOut: true, error: `operation exceeded ${maxWaitMs}ms` });
        return;
      }
      finish({ ok: false, error: errorText(error) });
    };

    const finishOperationSuccess = () => {
      if (now() >= deadline) {
        finish({ ok: false, timedOut: true, error: `operation exceeded ${maxWaitMs}ms` });
        return;
      }
      finish({ ok: true });
    };

    const remainingMs = deadline - now();
    timerHandle = setTimer(finishAtDeadline, Math.max(0, remainingMs));
    try {
      Promise.resolve(operation()).then(
        finishOperationSuccess,
        finishOperationFailure,
      );
    } catch (error) {
      finishOperationFailure(error);
    }
  });
};

const baseRecord = ({ mode, label, maxWaitMs }) => ({
  schema: GUIDED_BROWSER_TIMING_SCHEMA,
  mode,
  label,
  clock: 'performance.now',
  max_wait_ms: maxWaitMs,
  request_sent_at_ms: null,
  response_received_at_ms: null,
  replay_started_at_ms: null,
  text_rendered_at_ms: null,
  elapsed_request_to_render_ms: null,
  elapsed_response_to_render_ms: null,
  elapsed_replay_to_render_ms: null,
  rendered_text: null,
  rendered_text_length: 0,
  status: 'not_started',
  error: null,
});

/** Measure a true operator-triggered request through text rendered in the page. */
export const measureTrueInference = async ({
  sendRequest,
  readRenderedText,
  isTextReady = defaultTextReady,
  maxWaitMs = DEFAULT_RENDER_TIMEOUT_MS,
  label = 'true_inference',
  now = defaultClock,
  requestAnimationFrame = defaultRequestAnimationFrame,
  cancelAnimationFrame = defaultCancelAnimationFrame,
  setTimer,
  clearTimer,
}) => {
  const record = baseRecord({ mode: 'true_inference', label, maxWaitMs });
  const requestSentAt = now();
  const deadline = requestSentAt + maxWaitMs;
  record.request_sent_at_ms = requestSentAt;
  try {
    const request = await awaitWithinDeadline({
      operation: sendRequest,
      maxWaitMs,
      deadlineMs: deadline,
      now,
      setTimer: setTimer ?? ((callback, delayMs) => setTimeout(callback, delayMs)),
      clearTimer: clearTimer ?? ((handle) => clearTimeout(handle)),
    });
    if (!request.ok) {
      record.status = request.timedOut ? 'request_timeout' : 'request_failed';
      record.error = request.error;
      return record;
    }
    const responseReceivedAt = now();
    if (responseReceivedAt >= deadline) {
      record.status = 'request_timeout';
      record.error = `operation exceeded ${maxWaitMs}ms`;
      return record;
    }
    record.response_received_at_ms = responseReceivedAt;
    const rendered = await waitForRenderedText({
      readRenderedText,
      isTextReady,
      maxWaitMs,
      deadlineMs: deadline,
      now,
      requestAnimationFrame,
      cancelAnimationFrame,
      ...(setTimer ? { setTimer } : {}),
      ...(clearTimer ? { clearTimer } : {}),
    });
    if (!rendered.ok) {
      record.status = rendered.error ? 'render_failed' : 'render_timeout';
      record.error = rendered.error ?? null;
      return record;
    }
    if (rendered.renderedAtMs === null || rendered.renderedAtMs >= deadline) {
      record.status = 'render_timeout';
      record.error = null;
      return record;
    }
    record.status = 'rendered';
    record.text_rendered_at_ms = rendered.renderedAtMs;
    record.rendered_text = rendered.text;
    record.rendered_text_length = rendered.text.length;
    record.elapsed_request_to_render_ms = elapsed(requestSentAt, rendered.renderedAtMs);
    record.elapsed_response_to_render_ms = elapsed(responseReceivedAt, rendered.renderedAtMs);
    return record;
  } catch (error) {
    record.status = 'request_failed';
    record.error = errorText(error);
    return record;
  }
};

/**
 * Measure the same render observation for a recorded replay. It deliberately
 * leaves request/response timings null and reports a replay elapsed field.
 */
export const measureRecordedReplay = async ({
  triggerReplay,
  readRenderedText,
  isTextReady = defaultTextReady,
  maxWaitMs = DEFAULT_RENDER_TIMEOUT_MS,
  label = 'recorded_replay',
  now = defaultClock,
  requestAnimationFrame = defaultRequestAnimationFrame,
  cancelAnimationFrame = defaultCancelAnimationFrame,
  setTimer,
  clearTimer,
}) => {
  const record = baseRecord({ mode: 'recorded_replay', label, maxWaitMs });
  const replayStartedAt = now();
  const deadline = replayStartedAt + maxWaitMs;
  record.replay_started_at_ms = replayStartedAt;
  try {
    const replay = await awaitWithinDeadline({
      operation: triggerReplay,
      maxWaitMs,
      deadlineMs: deadline,
      now,
      setTimer: setTimer ?? ((callback, delayMs) => setTimeout(callback, delayMs)),
      clearTimer: clearTimer ?? ((handle) => clearTimeout(handle)),
    });
    if (!replay.ok) {
      record.status = replay.timedOut ? 'replay_timeout' : 'replay_failed';
      record.error = replay.error;
      return record;
    }
    if (now() >= deadline) {
      record.status = 'replay_timeout';
      record.error = `operation exceeded ${maxWaitMs}ms`;
      return record;
    }
    const rendered = await waitForRenderedText({
      readRenderedText,
      isTextReady,
      maxWaitMs,
      deadlineMs: deadline,
      now,
      requestAnimationFrame,
      cancelAnimationFrame,
      ...(setTimer ? { setTimer } : {}),
      ...(clearTimer ? { clearTimer } : {}),
    });
    if (!rendered.ok) {
      record.status = rendered.error ? 'render_failed' : 'render_timeout';
      record.error = rendered.error ?? null;
      return record;
    }
    if (rendered.renderedAtMs === null || rendered.renderedAtMs >= deadline) {
      record.status = 'render_timeout';
      record.error = null;
      return record;
    }
    record.status = 'rendered';
    record.text_rendered_at_ms = rendered.renderedAtMs;
    record.rendered_text = rendered.text;
    record.rendered_text_length = rendered.text.length;
    record.elapsed_replay_to_render_ms = elapsed(replayStartedAt, rendered.renderedAtMs);
    return record;
  } catch (error) {
    record.status = 'replay_failed';
    record.error = errorText(error);
    return record;
  }
};

/** Convenience reader for an element selected by the operator's browser harness. */
export const readRenderedTextFromSelector = (selector) => () =>
  document.querySelector(selector)?.textContent ?? '';

export const serializeGuidedBrowserTiming = (record) => JSON.stringify(record, null, 2);
