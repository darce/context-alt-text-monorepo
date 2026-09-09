export const POLL_TIMEOUT_MESSAGE =
  'This description is taking longer than expected. Please wait a moment, then refresh the page before trying again.';

// The public browser contract ceiling is 120 seconds, not a default derived
// from the server's GPU warm-up or inference budget.
export const PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS = 120;

export const PUBLIC_DEMO_ERROR_CODE = Object.freeze({
  POLL_TIMEOUT: 'acx_public_demo_poll_timeout',
  REQUEST_ABORTED: 'acx_public_demo_request_aborted',
  INVALID_RESPONSE: 'acx_public_demo_invalid_response',
  INCOMPLETE_RESULT: 'acx_public_demo_incomplete_result',
  PIPELINE_FAILED: 'acx_public_demo_pipeline_failed',
});

const STATUSES = new Set(['pending', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled']);
const PHASES = new Set(['queued', 'warming', 'describing', 'complete', 'failed', 'cancelled']);
const GPU_STATES = new Set(['unknown', 'stopped', 'starting', 'warming', 'ready', 'degraded']);
const DESCRIPTION_RESULT_TIERS = new Set(['provisional_cpu', 'final_gpu']);

export class PublicDemoClientError extends Error {
  constructor(code, message, status = 0) {
    super(message);
    this.name = 'PublicDemoClientError';
    this.code = code;
    this.status = status;
  }
}

const invalidResponse = () => new PublicDemoClientError(
  PUBLIC_DEMO_ERROR_CODE.INVALID_RESPONSE,
  'The demo returned an invalid response. Please refresh the page and try again.',
);
const timeoutError = () => new PublicDemoClientError(PUBLIC_DEMO_ERROR_CODE.POLL_TIMEOUT, POLL_TIMEOUT_MESSAGE);
const requestAbortedError = () => new PublicDemoClientError(
  PUBLIC_DEMO_ERROR_CODE.REQUEST_ABORTED,
  'The demo request was stopped because the page is closing.',
);

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const isCounter = (value) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;

/** Validate and narrow the anonymous REST boundary before presentation uses it. */
export const parsePublicDemoEnvelope = (body) => {
  if (!isRecord(body) || typeof body.run_id !== 'string' || body.run_id.trim() === '') {
    throw invalidResponse();
  }
  if (typeof body.status !== 'string' || !STATUSES.has(body.status)) {
    throw invalidResponse();
  }
  if (typeof body.phase !== 'string' || !PHASES.has(body.phase)) {
    throw invalidResponse();
  }
  const hasGpuState = Object.prototype.hasOwnProperty.call(body, 'gpu_state');
  if (hasGpuState && body.gpu_state !== null && (typeof body.gpu_state !== 'string' || !GPU_STATES.has(body.gpu_state))) {
    throw invalidResponse();
  }
  if (!isRecord(body.progress) || !isCounter(body.progress.done) || !isCounter(body.progress.total)) {
    throw invalidResponse();
  }
  if (body.progress.done > body.progress.total) {
    throw invalidResponse();
  }
  if (body.description !== undefined && typeof body.description !== 'string') {
    throw invalidResponse();
  }
  if (
    body.error !== undefined
    && (!isRecord(body.error)
      || typeof body.error.code !== 'string'
      || body.error.code.trim() === ''
      || typeof body.error.message !== 'string'
      || body.error.message.trim() === '')
  ) {
    throw invalidResponse();
  }
  if (
    body.deadline_seconds !== undefined
    && (typeof body.deadline_seconds !== 'number'
      || !Number.isSafeInteger(body.deadline_seconds)
      || body.deadline_seconds <= 0)
  ) {
    throw invalidResponse();
  }

  const expectedPhase = {
    pending: 'queued',
    completed: 'complete',
    completed_with_errors: 'complete',
    failed: 'failed',
    cancelled: 'cancelled',
  }[body.status];
  if (expectedPhase !== undefined && body.phase !== expectedPhase) {
    throw invalidResponse();
  }
  if (body.status === 'running' && !['warming', 'describing'].includes(body.phase)) {
    throw invalidResponse();
  }

  const description = typeof body.description === 'string' ? body.description.trim() : '';
  const hasCompletedDescription = body.status === 'completed' && description !== '';
  let descriptionTier;
  if (hasCompletedDescription) {
    if (Object.prototype.hasOwnProperty.call(body, 'description_tier')) {
      descriptionTier = body.description_tier;
      if (
        descriptionTier !== null
        && (typeof descriptionTier !== 'string' || !DESCRIPTION_RESULT_TIERS.has(descriptionTier))
      ) {
        throw invalidResponse();
      }
    } else {
      descriptionTier = null;
    }
  }

  return {
    run_id: body.run_id,
    status: body.status,
    phase: body.phase,
    progress: { done: body.progress.done, total: body.progress.total },
    ...(hasGpuState ? { gpu_state: body.gpu_state } : {}),
    ...(typeof body.deadline_seconds === 'number' ? { deadline_seconds: body.deadline_seconds } : {}),
    ...(typeof body.description === 'string' ? { description } : {}),
    ...(hasCompletedDescription ? { description_tier: descriptionTier } : {}),
    ...(isRecord(body.error) ? { error: { code: body.error.code, message: body.error.message } } : {}),
  };
};

const defaultSleep = (milliseconds) => new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));

const generateIdempotencyKey = () => {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return `acx-demo-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
};

const waitForBackoff = async ({ sleep, milliseconds, deadlineAt, now, navigationSignal }) => {
  if (navigationSignal?.aborted) throw requestAbortedError();

  const remaining = deadlineAt - now();
  if (remaining <= 0) throw timeoutError();

  let rejectDeadline;
  let rejectNavigation;
  const deadlinePromise = new Promise((_resolve, reject) => {
    rejectDeadline = reject;
  });
  const navigationPromise = new Promise((_resolve, reject) => {
    rejectNavigation = reject;
  });
  const timer = globalThis.setTimeout(() => rejectDeadline(timeoutError()), remaining);
  const onNavigation = () => rejectNavigation(requestAbortedError());
  navigationSignal?.addEventListener('abort', onNavigation, { once: true });

  try {
    await Promise.race([
      Promise.resolve().then(() => sleep(Math.min(milliseconds, remaining))),
      deadlinePromise,
      navigationPromise,
    ]);
  } finally {
    globalThis.clearTimeout(timer);
    navigationSignal?.removeEventListener('abort', onNavigation);
  }
};

const requestJson = async (url, options, fetchImpl, { deadlineAt, now, navigationSignal }) => {
  const controller = new AbortController();
  let abortKind = '';
  let rejectAbort;
  const abortPromise = new Promise((_resolve, reject) => {
    rejectAbort = reject;
  });
  const abort = (kind) => {
    if (controller.signal.aborted) return;
    abortKind = kind;
    controller.abort();
    rejectAbort(new DOMException('The request was aborted.', 'AbortError'));
  };
  const remaining = Math.max(0, deadlineAt - now());
  const timer = globalThis.setTimeout(() => abort('deadline'), remaining);
  const onNavigation = () => abort('navigation');
  navigationSignal?.addEventListener('abort', onNavigation, { once: true });
  if (navigationSignal?.aborted) abort('navigation');

  try {
    const response = await Promise.race([
      fetchImpl(url, { ...options, signal: controller.signal }),
      abortPromise,
    ]);
    let body = null;
    try {
      body = await Promise.race([response.json(), abortPromise]);
    } catch (error) {
      if (abortKind) throw error;
      // The exhaustive parser below owns the typed invalid-response fallback.
    }

    if (!response.ok) {
      throw new PublicDemoClientError(
        typeof body?.code === 'string' ? body.code : PUBLIC_DEMO_ERROR_CODE.INVALID_RESPONSE,
        typeof body?.message === 'string' ? body.message : 'The demo request could not be completed.',
        response.status,
      );
    }
    return body;
  } catch (error) {
    if (abortKind === 'deadline') {
      throw timeoutError();
    }
    if (abortKind === 'navigation') {
      throw requestAbortedError();
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
    navigationSignal?.removeEventListener('abort', onNavigation);
  }
};

const terminalFailure = (body) => {
  if (body.error) {
    return new PublicDemoClientError(body.error.code, body.error.message);
  }
  return new PublicDemoClientError(
    PUBLIC_DEMO_ERROR_CODE.PIPELINE_FAILED,
    'The image could not be described. Please try again later.',
  );
};

export const pollRun = async ({
  statusUrl,
  nonce,
  fetchImpl = fetch,
  sleep = defaultSleep,
  now = Date.now,
  timeoutMs = PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS * 1_000,
  navigationSignal,
  onUpdate = () => {},
}) => {
  const deadlineAt = now() + timeoutMs;
  let delay = 500;
  const timedOut = () => now() >= deadlineAt;

  while (!timedOut()) {
    if (navigationSignal?.aborted) throw requestAbortedError();
    const raw = await requestJson(
      statusUrl,
      { method: 'GET', credentials: 'same-origin', headers: { 'X-WP-Nonce': nonce } },
      fetchImpl,
      { deadlineAt, now, navigationSignal },
    );
    if (timedOut()) throw timeoutError();

    const body = parsePublicDemoEnvelope(raw);
    onUpdate(body);
    if (body.status === 'completed') {
      if (!body.description) {
        throw new PublicDemoClientError(
          PUBLIC_DEMO_ERROR_CODE.INCOMPLETE_RESULT,
          'The description finished without a usable result. Please try another image.',
        );
      }
      return body;
    }
    if (['completed_with_errors', 'failed', 'cancelled'].includes(body.status)) {
      throw terminalFailure(body);
    }

    await waitForBackoff({ sleep, milliseconds: delay, deadlineAt, now, navigationSignal });
    delay = Math.min(delay * 2, 5_000);
  }

  throw timeoutError();
};

export const statusPresentation = (body) => {
  if (body.phase === 'warming') {
    return { state: 'warming', message: 'The description service is warming up. A cold start can take several minutes…' };
  }
  if (body.phase === 'queued') {
    return { state: 'queued', message: 'Your image is queued for description…' };
  }
  if (body.phase === 'describing') {
    const progress = body.progress.total > 0 ? Math.round((body.progress.done / body.progress.total) * 100) : null;
    return { state: 'describing', message: progress === null ? 'Describing the image…' : `Describing the image… ${progress}%` };
  }
  if (body.phase === 'complete' && body.status === 'completed') {
    return { state: 'completed', message: 'Description complete.' };
  }
  return { state: 'failed', message: body.error?.message ?? 'The image could not be described. Please try again later.' };
};

export const initializeDemo = (root) => {
  const form = root.querySelector('.acx-demo__form');
  const statusMessage = root.querySelector('[data-acx-demo-message]');
  const statusIcon = root.querySelector('[data-acx-demo-icon]');
  const result = root.querySelector('[data-acx-demo-result]');
  if (!(form instanceof HTMLFormElement) || !(statusMessage instanceof HTMLElement) || !(result instanceof HTMLElement)) return;

  let retryKey = null;
  let retryMedia = null;

  const setState = (state, message) => {
    root.dataset.state = state;
    statusMessage.textContent = message;
    if (statusIcon instanceof HTMLElement) {
      statusIcon.textContent = { idle: '●', queued: '◌', warming: '◌', describing: '◌', completed: '✓', limited: '!', failed: '×', error: '×' }[state] ?? '●';
    }
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    // PHP unique groups are `acx-demo-media-<instance>`; query only this form.
    const selectedRadio = form.querySelector('input[type="radio"]:checked');
    const selected = selectedRadio instanceof HTMLInputElement ? selectedRadio.value : null;
    if (typeof selected !== 'string' || !/^\d+$/.test(selected)) {
      setState('error', 'Choose an image before requesting a description.');
      return;
    }

    if (retryKey === null || retryMedia !== selected) {
      retryKey = generateIdempotencyKey();
      retryMedia = selected;
    }

    const controls = Array.from(form.elements);
    controls.forEach((control) => { control.disabled = true; });
    result.hidden = true;
    result.textContent = '';
    setState('queued', 'Starting the description…');
    const navigation = new AbortController();
    const stopForNavigation = () => navigation.abort();
    globalThis.addEventListener('pagehide', stopForNavigation, { once: true });

    try {
      const submitDeadline = Date.now() + 30_000;
      const submitted = parsePublicDemoEnvelope(await requestJson(
        root.dataset.submitUrl ?? '',
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-WP-Nonce': root.dataset.nonce ?? '' },
          body: JSON.stringify({ media_id: Number(selected), idempotency_key: retryKey }),
        },
        fetch,
        { deadlineAt: submitDeadline, now: Date.now, navigationSignal: navigation.signal },
      ));
      if (!submitted.deadline_seconds) throw invalidResponse();

      const finalState = await pollRun({
        statusUrl: `${root.dataset.submitUrl}/runs/${encodeURIComponent(submitted.run_id)}`,
        nonce: root.dataset.nonce ?? '',
        timeoutMs: Math.min(
          submitted.deadline_seconds,
          PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS,
        ) * 1_000,
        navigationSignal: navigation.signal,
        onUpdate: (update) => {
          const presentation = statusPresentation(update);
          setState(presentation.state, presentation.message);
        },
      });

      result.textContent = finalState.description;
      result.hidden = false;
      result.focus();
      setState('completed', 'Description complete.');
      retryKey = null;
      retryMedia = null;
    } catch (error) {
      setState(
        error instanceof PublicDemoClientError && error.status === 429 ? 'limited' : 'failed',
        error instanceof Error ? error.message : 'The demo request could not be completed.',
      );
    } finally {
      globalThis.removeEventListener('pagehide', stopForNavigation);
      controls.forEach((control) => { control.disabled = false; });
    }
  });
};

const initializeAll = () => document.querySelectorAll('[data-acx-demo]').forEach(initializeDemo);

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeAll, { once: true });
  } else {
    initializeAll();
  }
}
