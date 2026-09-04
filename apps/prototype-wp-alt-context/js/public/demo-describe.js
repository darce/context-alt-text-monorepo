export const POLL_TIMEOUT_MESSAGE =
  'This description is taking longer than expected. Please wait a moment, then refresh the page before trying again.';

export const PUBLIC_DEMO_ERROR_CODE = Object.freeze({
  POLL_TIMEOUT: 'acx_public_demo_poll_timeout',
  INVALID_RESPONSE: 'acx_public_demo_invalid_response',
});

const TERMINAL_STATUSES = new Set(['completed', 'completed_with_errors', 'failed', 'cancelled']);

export class PublicDemoClientError extends Error {
  constructor(code, message, status = 0) {
    super(message);
    this.name = 'PublicDemoClientError';
    this.code = code;
    this.status = status;
  }
}

const defaultSleep = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

const requestJson = async (url, options, fetchImpl) => {
  const response = await fetchImpl(url, options);
  let body = null;
  try {
    body = await response.json();
  } catch {
    // A typed fallback keeps presentation logic independent from response text.
  }

  if (!response.ok) {
    throw new PublicDemoClientError(
      typeof body?.code === 'string' ? body.code : PUBLIC_DEMO_ERROR_CODE.INVALID_RESPONSE,
      typeof body?.message === 'string' ? body.message : 'The demo request could not be completed.',
      response.status,
    );
  }
  if (body === null || typeof body !== 'object') {
    throw new PublicDemoClientError(
      PUBLIC_DEMO_ERROR_CODE.INVALID_RESPONSE,
      'The demo returned an unreadable response.',
      response.status,
    );
  }

  return body;
};

export const pollRun = async ({
  statusUrl,
  nonce,
  fetchImpl = fetch,
  sleep = defaultSleep,
  now = Date.now,
  timeoutMs = 120_000,
  onUpdate = () => {},
}) => {
  const startedAt = now();
  let delay = 500;

  while (now() - startedAt < timeoutMs) {
    const body = await requestJson(
      statusUrl,
      { method: 'GET', credentials: 'same-origin', headers: { 'X-WP-Nonce': nonce } },
      fetchImpl,
    );
    onUpdate(body);
    if (typeof body.status === 'string' && TERMINAL_STATUSES.has(body.status)) {
      return body;
    }

    await sleep(delay);
    delay = Math.min(delay * 2, 5_000);
  }

  throw new PublicDemoClientError(PUBLIC_DEMO_ERROR_CODE.POLL_TIMEOUT, POLL_TIMEOUT_MESSAGE);
};

const descriptionFrom = (body) => {
  const candidates = [
    body.description,
    body.alt_text,
    body.result?.description,
    body.result?.alt_text,
    Array.isArray(body.items) ? body.items[0]?.draft_alt_text : null,
  ];
  return candidates.find((value) => typeof value === 'string' && value.trim() !== '') ?? '';
};

const initializeDemo = (root) => {
  const form = root.querySelector('.acx-demo__form');
  const statusMessage = root.querySelector('[data-acx-demo-message]');
  const statusIcon = root.querySelector('[data-acx-demo-icon]');
  const result = root.querySelector('[data-acx-demo-result]');
  if (!(form instanceof HTMLFormElement) || !(statusMessage instanceof HTMLElement) || !(result instanceof HTMLElement)) {
    return;
  }

  const setState = (state, message) => {
    root.dataset.state = state;
    statusMessage.textContent = message;
    if (statusIcon instanceof HTMLElement) {
      statusIcon.textContent = { idle: '●', running: '◌', done: '✓', limited: '!', error: '×' }[state] ?? '●';
    }
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const selected = new FormData(form).get('acx-demo-media');
    if (typeof selected !== 'string' || !/^\d+$/.test(selected)) {
      setState('error', 'Choose an image before requesting a description.');
      return;
    }

    const controls = Array.from(form.elements);
    controls.forEach((control) => {
      control.disabled = true;
    });
    result.hidden = true;
    result.textContent = '';
    setState('running', 'Starting the description…');

    try {
      const submitted = await requestJson(
        root.dataset.submitUrl ?? '',
        {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-WP-Nonce': root.dataset.nonce ?? '' },
          body: JSON.stringify({ media_id: Number(selected) }),
        },
        fetch,
      );
      if (typeof submitted.run_id !== 'string' || submitted.run_id === '') {
        throw new PublicDemoClientError(
          PUBLIC_DEMO_ERROR_CODE.INVALID_RESPONSE,
          'The demo did not return a status link.',
        );
      }

      const finalState = await pollRun({
        statusUrl: `${root.dataset.submitUrl}/runs/${encodeURIComponent(submitted.run_id)}`,
        nonce: root.dataset.nonce ?? '',
        onUpdate: (update) => {
          const completed = Number(update.completed);
          const total = Number(update.total);
          const progress = total > 0 ? Math.round((completed / total) * 100) : Number.NaN;
          setState(
            'running',
            Number.isFinite(progress) ? `Describing the image… ${Math.max(0, Math.min(100, progress))}%` : 'Describing the image…',
          );
        },
      });

      if (finalState.status === 'completed' || finalState.status === 'completed_with_errors') {
        const description = descriptionFrom(finalState);
        result.textContent = description || 'The description finished. Select another image to try the demo again.';
        result.hidden = false;
        result.focus();
        setState('done', 'Description complete.');
      } else {
        setState('error', 'The image could not be described. Please try again later.');
      }
    } catch (error) {
      setState(
        error instanceof PublicDemoClientError && error.status === 429 ? 'limited' : 'error',
        error instanceof Error ? error.message : 'The demo request could not be completed.',
      );
    } finally {
      controls.forEach((control) => {
        control.disabled = false;
      });
    }
  });
};

const initializeAll = () => {
  document.querySelectorAll('[data-acx-demo]').forEach(initializeDemo);
};

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeAll, { once: true });
  } else {
    initializeAll();
  }
}
