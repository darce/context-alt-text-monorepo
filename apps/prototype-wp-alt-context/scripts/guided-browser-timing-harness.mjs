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
  maxWaitMs = DEFAULT_RENDER_TIMEOUT_MS,
  now = defaultClock,
  requestAnimationFrame = defaultRequestAnimationFrame,
  cancelAnimationFrame = defaultCancelAnimationFrame,
  setTimer = (callback, delayMs) => setTimeout(callback, delayMs),
  clearTimer = (handle) => clearTimeout(handle),
}) => {
  if (!Number.isFinite(maxWaitMs) || maxWaitMs <= 0) {
    throw new Error('maxWaitMs must be a finite number greater than zero');
  }

  const deadline = now() + maxWaitMs;

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
      const observedAt = now();
      let text;
      try {
        text = String(readRenderedText() ?? '');
      } catch (error) {
        finish({ ok: false, text: null, renderedAtMs: null, error: errorText(error) });
        return;
      }
      if (isTextReady(text)) {
        finish({ ok: true, text, renderedAtMs: observedAt });
        return;
      }
      if (observedAt >= deadline) {
        finish({ ok: false, text: null, renderedAtMs: null, timedOut: true });
        return;
      }
      frameHandle = requestAnimationFrame(inspect);
    };

    frameHandle = requestAnimationFrame(inspect);
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
    timerHandle = setTimer(finishAtDeadline, maxWaitMs);
  });
};

const awaitWithinDeadline = async ({ operation, maxWaitMs, now, setTimer, clearTimer }) => {
  const deadline = now() + maxWaitMs;
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

    timerHandle = setTimer(finishAtDeadline, maxWaitMs);
    try {
      Promise.resolve(operation()).then(
        () => finish({ ok: true }),
        (error) => finish({ ok: false, error: errorText(error) }),
      );
    } catch (error) {
      finish({ ok: false, error: errorText(error) });
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
  record.request_sent_at_ms = requestSentAt;
  try {
    const request = await awaitWithinDeadline({
      operation: sendRequest,
      maxWaitMs,
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
    record.response_received_at_ms = responseReceivedAt;
    const rendered = await waitForRenderedText({
      readRenderedText,
      isTextReady,
      maxWaitMs,
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
  record.replay_started_at_ms = replayStartedAt;
  try {
    const replay = await awaitWithinDeadline({
      operation: triggerReplay,
      maxWaitMs,
      now,
      setTimer: setTimer ?? ((callback, delayMs) => setTimeout(callback, delayMs)),
      clearTimer: clearTimer ?? ((handle) => clearTimeout(handle)),
    });
    if (!replay.ok) {
      record.status = replay.timedOut ? 'replay_timeout' : 'replay_failed';
      record.error = replay.error;
      return record;
    }
    const rendered = await waitForRenderedText({
      readRenderedText,
      isTextReady,
      maxWaitMs,
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
