// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS,
  PublicDemoClientError,
  parsePublicDemoEnvelope,
  pollRun,
  statusPresentation,
  initializeDemo,
} from '../demo-describe.js';

const TIMEOUT_COPY = 'This is taking longer than expected. The description may still finish: choose Describe again with the same image to check on it.';
const COLD_START_COPY = 'The first description after a quiet period starts the GPU and can take several minutes. After that, each image takes seconds.';
const STOPPED_COPY = 'Stopped waiting. The image may still be described: choose Describe again with the same image to see the result.';

const radioFixtureDir = join(dirname(fileURLToPath(import.meta.url)), 'fixtures/public-demo-radio');
const ACTUAL_SHORTCODE_TWO_INSTANCES = readFileSync(join(radioFixtureDir, 'two-instances.html'), 'utf8');
const RADIO_SOURCE_ANCHORS = JSON.parse(
  readFileSync(join(radioFixtureDir, 'source-anchors.json'), 'utf8'),
) as {
  expected_names: string[];
  forbidden_simplified_name: string;
  source_anchors: {
    php_group_name: { literal: string };
    js_formdata_lookup: { literal: string };
  };
};

const running = (overrides: Record<string, unknown> = {}) => ({
  run_id: 'run-1',
  status: 'running',
  phase: 'describing',
  gpu_state: 'ready',
  progress: { done: 0, total: 1 },
  ...overrides,
});

const response = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('public demo describe polling', () => {
  it('carries the submit capability on status polls so completion can be replayed', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(response(running({
      status: 'completed', phase: 'complete', description: 'A lakeside path.',
    })));
    await pollRun({ statusUrl: '/status/run-1', nonce: 'nonce', idempotencyKey: 'resume-key-1234', fetchImpl });
    const options = fetchImpl.mock.calls[0]?.[1];
    expect(new Headers(options?.headers).get('Idempotency-Key')).toBe('resume-key-1234');
  });

  it('backs off exponentially and stops polling on a terminal response', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(running({ status: 'pending', phase: 'queued' })))
      .mockResolvedValueOnce(response(running()))
      .mockResolvedValueOnce(response(running({ status: 'completed', phase: 'complete', progress: { done: 1, total: 1 }, description: 'A lakeside path.' })));
    const waits: number[] = [];
    let clock = 0;

    const result = await pollRun({
      statusUrl: '/status/run-1',
      nonce: 'nonce',
      fetchImpl,
      now: () => clock,
      sleep: async (milliseconds: number) => {
        waits.push(milliseconds);
        clock += milliseconds;
      },
    });

    expect(waits).toEqual([500, 1_000]);
    expect(result.status).toBe('completed');
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('caps polling intervals at five seconds', async () => {
    const statuses = Array.from({ length: 7 }, () => response(running()));
    statuses.push(response(running({ status: 'failed', phase: 'failed', error: { code: 'acx_public_demo_pipeline_failed', message: 'The image could not be described.' } })));
    const fetchImpl = vi.fn<typeof fetch>();
    for (const item of statuses) {
      fetchImpl.mockResolvedValueOnce(item);
    }
    const waits: number[] = [];
    let clock = 0;

    await expect(pollRun({
      statusUrl: '/status/run-2',
      nonce: 'nonce',
      fetchImpl,
      now: () => clock,
      sleep: async (milliseconds: number) => {
        waits.push(milliseconds);
        clock += milliseconds;
      },
    })).rejects.toMatchObject({ code: 'acx_public_demo_pipeline_failed' });

    expect(waits).toEqual([500, 1_000, 2_000, 4_000, 5_000, 5_000, 5_000]);
  });

  it('hard-stops after the configured polling deadline with operator-friendly copy', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => response(running()));
    let clock = 0;

    await expect(
      pollRun({
        statusUrl: '/status/run-3',
        nonce: 'nonce',
        fetchImpl,
        timeoutMs: 1_200,
        now: () => clock,
        sleep: async (milliseconds: number) => {
          clock += milliseconds;
        },
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_poll_timeout', message: TIMEOUT_COPY });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('reports a deadline breach before an invalid response that arrives too late', async () => {
    let clock = 0;
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => {
      clock = 1_200;
      return response(null);
    });

    await expect(
      pollRun({
        statusUrl: '/status/run-too-late',
        nonce: 'nonce',
        fetchImpl,
        timeoutMs: 1_200,
        now: () => clock,
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_poll_timeout', message: TIMEOUT_COPY });
  });

  it('surfaces typed REST errors instead of polling again', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response({ code: 'acx_public_demo_busy', message: 'Another run is active.' }, 429));

    await expect(
      pollRun({ statusUrl: '/status/run-4', nonce: 'nonce', fetchImpl }),
    ).rejects.toEqual(new PublicDemoClientError('acx_public_demo_busy', 'Another run is active.', 429));
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it.each([
    [],
    {},
    running({ status: 'surprise' }),
    running({ status: 'pending', phase: 'describing' }),
    running({ progress: { done: -1, total: 1 } }),
    running({ progress: { done: 2, total: 1 } }),
    running({ progress: { done: 0.5, total: 1 } }),
    running({ progress: { done: '0', total: 1 } }),
    running({ progress: { total: 1 } }),
  ])('rejects malformed success envelopes immediately', async (payload) => {
    await expect(
      pollRun({ statusUrl: '/status/malformed', nonce: 'nonce', fetchImpl: vi.fn(async () => response(payload)) }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_invalid_response' });
  });

  it('requires a non-empty description for a completed run', async () => {
    await expect(
      pollRun({
        statusUrl: '/status/no-draft',
        nonce: 'nonce',
        fetchImpl: vi.fn(async () => response(running({ status: 'completed', phase: 'complete', progress: { done: 1, total: 1 } }))),
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_incomplete_result' });
  });

  it('treats completed_with_errors as a typed failure', async () => {
    const presentations: ReturnType<typeof statusPresentation>[] = [];
    await expect(
      pollRun({
        statusUrl: '/status/partial',
        nonce: 'nonce',
        fetchImpl: vi.fn(async () => response(running({
          status: 'completed_with_errors',
          phase: 'complete',
          progress: { done: 1, total: 1 },
          error: { code: 'acx_public_demo_partial_failure', message: 'The description did not complete successfully.' },
        }))),
        onUpdate: (update) => presentations.push(statusPresentation(update)),
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_partial_failure' });
    expect(presentations.length).toBeGreaterThan(0);
    expect(presentations.every(({ state, message }) => state !== 'completed' && !/description complete/i.test(message))).toBe(true);
  });

  it('aborts an in-flight fetch at the remaining deadline', async () => {
    const fetchImpl = vi.fn<typeof fetch>((_input, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
    }));

    await expect(
      pollRun({ statusUrl: '/status/hung', nonce: 'nonce', fetchImpl, timeoutMs: 10 }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_poll_timeout' });
    expect(fetchImpl.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal);
    expect(fetchImpl.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  });

  it('aborts an in-flight fetch when navigation starts', async () => {
    const navigation = new AbortController();
    const fetchImpl = vi.fn<typeof fetch>((_input, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
      navigation.abort();
    }));

    await expect(
      pollRun({ statusUrl: '/status/leaving', nonce: 'nonce', fetchImpl, navigationSignal: navigation.signal }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_request_aborted' });
  });

  it('reports navigation during the five-second backoff as an aborted degradation path', async () => {
    const navigation = new AbortController();
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => response(running()));
    let waits = 0;

    await expect(
      pollRun({
        statusUrl: '/status/backoff-navigation',
        nonce: 'nonce',
        fetchImpl,
        navigationSignal: navigation.signal,
        sleep: async (milliseconds: number) => {
          waits += 1;
          if (milliseconds === 5_000) {
            navigation.abort();
            return new Promise<void>(() => {});
          }
        },
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_request_aborted' });

    expect(waits).toBe(5);
    expect(fetchImpl).toHaveBeenCalledTimes(5);
  });

  it.each([
    { gpu_state: null },
    { gpu_state: undefined },
  ])('preserves null and absent gpu_state without inventing metadata', ({ gpu_state }) => {
    const payload: Record<string, unknown> = running();
    if (gpu_state === undefined) delete payload.gpu_state;
    else payload.gpu_state = gpu_state;

    const parsed = parsePublicDemoEnvelope(payload);
    expect(Object.prototype.hasOwnProperty.call(parsed, 'gpu_state')).toBe(gpu_state !== undefined);
    if (gpu_state === null) expect(parsed.gpu_state).toBeNull();
  });

  it('renders warming and describing phases honestly', () => {
    expect(statusPresentation(parsePublicDemoEnvelope(running({ phase: 'warming', gpu_state: 'starting' }))).message).toBe(COLD_START_COPY);
    const previousLang = document.documentElement.lang;
    try {
      document.documentElement.lang = 'en-US';
      expect(statusPresentation(parsePublicDemoEnvelope(running({ phase: 'describing', progress: { done: 1, total: 2 } }))).message).toContain('50%');
    } finally {
      document.documentElement.lang = previousLang;
    }
  });

  it('clamps a large server deadline to the browser contract ceiling', async () => {
    vi.useFakeTimers();
    // Simplified name="acx-demo-media" harness for deadline/polling only.
    // GPU-LAUNCH-PUBLIC-RADIO-01 coverage uses fixtures/public-demo-radio/.
    document.body.innerHTML = `
      <div data-acx-demo data-submit-url="/submit" data-nonce="nonce">
        <form class="acx-demo__form">
          <input type="radio" name="acx-demo-media" value="41" checked>
          <button type="submit">Describe</button>
        </form>
        <span data-acx-demo-icon></span>
        <p data-acx-demo-message></p>
        <p data-acx-demo-result tabindex="-1"></p>
      </div>`;
    const root = document.querySelector<HTMLElement>('[data-acx-demo]');
    const form = root?.querySelector<HTMLFormElement>('form');
    let pollSignal: AbortSignal | undefined;
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(running({ status: 'pending', phase: 'queued', deadline_seconds: 690 })))
      .mockImplementationOnce((_input, init) => new Promise<Response>((_resolve, reject) => {
        pollSignal = init?.signal ?? undefined;
        pollSignal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
      }));
    vi.stubGlobal('fetch', fetchImpl);

    try {
      initializeDemo(root as HTMLElement);
      form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await vi.advanceTimersByTimeAsync(PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS * 1_000);
      await Promise.resolve();

      expect(pollSignal?.aborted).toBe(true);
      expect(root?.querySelector('[data-acx-demo-message]')?.textContent).toBe(TIMEOUT_COPY);
    } finally {
      vi.unstubAllGlobals();
      vi.useRealTimers();
      document.body.innerHTML = '';
    }
  });

  it('reuses a trigger key for a retry and mints a new key after completion', async () => {
    // Simplified name="acx-demo-media" harness for retry-key behaviour only.
    document.body.innerHTML = `
      <div data-acx-demo data-submit-url="/submit" data-nonce="nonce">
        <form class="acx-demo__form">
          <input type="radio" name="acx-demo-media" value="41" checked>
          <button type="submit">Describe</button>
        </form>
        <span data-acx-demo-icon></span>
        <p data-acx-demo-message></p>
        <p data-acx-demo-result tabindex="-1"></p>
      </div>`;
    const root = document.querySelector<HTMLElement>('[data-acx-demo]');
    const form = root?.querySelector<HTMLFormElement>('form');
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new Error('response dropped'))
      .mockResolvedValueOnce(response(running({ status: 'pending', phase: 'queued', deadline_seconds: 1 })))
      .mockResolvedValueOnce(response(running({ status: 'completed', phase: 'complete', progress: { done: 1, total: 1 }, description: 'A lakeside path.' })))
      .mockRejectedValueOnce(new Error('new trigger failed'));
    vi.stubGlobal('fetch', fetchImpl);

    // The handler disables every form control while a request is in flight, and
    // FormData skips disabled controls -- so a submit dispatched before the
    // previous cycle settles reads no media_id and returns without fetching.
    // Counting microtasks to guess when that happened is what made this case
    // read fetch call #1 before it existed. Drive it off observable state.
    const settle = async (predicate: () => boolean): Promise<void> => {
      for (let tick = 0; tick < 200; tick += 1) {
        if (predicate()) return;
        await Promise.resolve();
        await new Promise((resolve) => { setTimeout(resolve, 0); });
      }
      throw new Error('timed out waiting for the demo client to settle');
    };
    const submitButton = () => form?.querySelector<HTMLButtonElement>('button[type="submit"]');
    const calls = () => fetchImpl.mock.calls.length;
    const keyOf = (index: number): string => {
      const body = fetchImpl.mock.calls[index]?.[1]?.body;
      expect(body, `fetch call #${index} was never issued`).toBeDefined();
      return JSON.parse(String(body)).idempotency_key;
    };
    const submitAndSettle = async (expectedCalls: number): Promise<void> => {
      form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await settle(() => calls() >= expectedCalls && submitButton()?.disabled === false);
    };

    try {
      initializeDemo(root as HTMLElement);

      // Cycle 1: the submit POST is dropped, so the trigger key must survive.
      await submitAndSettle(1);
      const firstKey = keyOf(0);

      // Cycle 2: a retry of the same media reuses that key, then polls to
      // completion (POST + one status poll).
      await submitAndSettle(3);
      const retryKey = keyOf(1);
      expect(retryKey).toBe(firstKey);

      // Cycle 3: after a completed run the key is retired, not reused.
      await submitAndSettle(4);
      const freshKey = keyOf(3);
      expect(freshKey).not.toBe(retryKey);
    } finally {
      vi.unstubAllGlobals();
      document.body.innerHTML = '';
    }
  });

  it('re-enables form controls after a polling timeout', async () => {
    vi.useFakeTimers();
    // Simplified name="acx-demo-media" harness for control re-enable only.
    document.body.innerHTML = `
      <div data-acx-demo data-submit-url="/submit" data-nonce="nonce">
        <form class="acx-demo__form">
          <input type="radio" name="acx-demo-media" value="41" checked>
          <button type="submit">Describe</button>
        </form>
        <span data-acx-demo-icon></span>
        <p data-acx-demo-message></p>
        <p data-acx-demo-result tabindex="-1"></p>
      </div>`;
    const root = document.querySelector<HTMLElement>('[data-acx-demo]');
    const form = root?.querySelector<HTMLFormElement>('form');
    let pollSignal: AbortSignal | undefined;
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(running({ status: 'pending', phase: 'queued', gpu_state: 'stopped', deadline_seconds: 1 })))
      .mockImplementationOnce((_input, init) => new Promise<Response>((_resolve, reject) => {
        pollSignal = init?.signal ?? undefined;
        pollSignal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
      }));
    vi.stubGlobal('fetch', fetchImpl);

    try {
      expect(root).toBeInstanceOf(HTMLElement);
      expect(form).toBeInstanceOf(HTMLFormElement);
      initializeDemo(root as HTMLElement);
      form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      expect(Array.from(form?.elements ?? []).every((control) => (control as HTMLInputElement).disabled)).toBe(true);

      await vi.advanceTimersByTimeAsync(1_000);
      await Promise.resolve();

      expect(pollSignal?.aborted).toBe(true);
      expect(Array.from(form?.elements ?? []).every((control) => !(control as HTMLInputElement).disabled)).toBe(true);
      expect(root?.querySelector('[data-acx-demo-message]')?.textContent).toBe(TIMEOUT_COPY);
    } finally {
      vi.unstubAllGlobals();
      vi.useRealTimers();
      document.body.innerHTML = '';
    }
  });
});

describe('public demo description_tier envelope contract', () => {
  const completedDescription = (overrides: Record<string, unknown> = {}) =>
    running({
      status: 'completed',
      phase: 'complete',
      progress: { done: 1, total: 1 },
      description: 'A lakeside path.',
      ...overrides,
    });

  it.each([
    ['provisional_cpu', 'provisional_cpu'],
    ['final_gpu', 'final_gpu'],
    [null, null],
  ] as const)(
    'keeps description_tier %s on a completed description even when gpu_state is ready',
    (tier, expected) => {
      const parsed = parsePublicDemoEnvelope(
        completedDescription({ gpu_state: 'ready', description_tier: tier }),
      );

      expect(parsed.description).toBe('A lakeside path.');
      expect(parsed.gpu_state).toBe('ready');
      expect(Object.prototype.hasOwnProperty.call(parsed, 'description_tier')).toBe(true);
      expect(parsed.description_tier).toBe(expected);
    },
  );

  it('treats a legacy completed description without description_tier as explicit null', () => {
    const payload = completedDescription({ gpu_state: 'ready' });
    expect(Object.prototype.hasOwnProperty.call(payload, 'description_tier')).toBe(false);

    const parsed = parsePublicDemoEnvelope(payload);

    expect(parsed.description).toBe('A lakeside path.');
    expect(parsed.gpu_state).toBe('ready');
    expect(Object.prototype.hasOwnProperty.call(parsed, 'description_tier')).toBe(true);
    expect(parsed.description_tier).toBeNull();
  });

  it.each<[string, unknown]>([
    ['unknown string', 'unknown'],
    ['number', 1],
    ['array', ['final_gpu']],
  ])('rejects an explicit unknown description_tier with INVALID_RESPONSE (%s)', (_label, tier) => {
    expect(() => parsePublicDemoEnvelope(completedDescription({ description_tier: tier }))).toThrow(
      PublicDemoClientError,
    );
    try {
      parsePublicDemoEnvelope(completedDescription({ description_tier: tier }));
      expect.unreachable('invalid description_tier must not parse');
    } catch (error) {
      expect(error).toMatchObject({ code: 'acx_public_demo_invalid_response' });
    }
  });

  it.each([
    running({ description_tier: 'final_gpu' }),
    running({
      status: 'failed',
      phase: 'failed',
      error: { code: 'acx_public_demo_pipeline_failed', message: 'The image could not be described.' },
      description_tier: 'provisional_cpu',
    }),
    running({
      status: 'completed',
      phase: 'complete',
      progress: { done: 1, total: 1 },
      description_tier: 'final_gpu',
    }),
  ])('does not produce description_tier on noncompleted, error, or no-description payloads', (payload) => {
    const parsed = parsePublicDemoEnvelope(payload);
    expect(Object.prototype.hasOwnProperty.call(parsed, 'description_tier')).toBe(false);
  });

  it('returns the parsed description_tier from pollRun on a completed description', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValueOnce(
      response(
        completedDescription({
          gpu_state: 'ready',
          description_tier: 'final_gpu',
        }),
      ),
    );

    const result = await pollRun({ statusUrl: '/status/run-1', nonce: 'nonce', fetchImpl });

    expect(result.status).toBe('completed');
    expect(result.description).toBe('A lakeside path.');
    expect(result.gpu_state).toBe('ready');
    expect(result.description_tier).toBe('final_gpu');
  });
});

describe('public demo visible description_tier labels', () => {
  const DESCRIPTION = 'A lakeside path.';
  const LABEL = {
    final_gpu: 'GPU description complete.',
    provisional_cpu: 'CPU fallback draft (not GPU final).',
    unknown: 'Description available, processing tier unavailable.',
  } as const;

  const completedDescription = (overrides: Record<string, unknown> = {}): Record<string, unknown> =>
    running({
      status: 'completed',
      phase: 'complete',
      progress: { done: 1, total: 1 },
      description: DESCRIPTION,
      ...overrides,
    });

  const settle = async (predicate: () => boolean): Promise<void> => {
    for (let tick = 0; tick < 200; tick += 1) {
      if (predicate()) return;
      await Promise.resolve();
      await new Promise((resolve) => { setTimeout(resolve, 0); });
    }
    throw new Error('timed out waiting for the demo client to settle');
  };

  it('styles degraded status with the warning token and no literal colour fallback', () => {
    const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../demo-describe.css'), 'utf8');

    expect(css).toContain(".acx-demo[data-state='degraded'] .acx-demo__status");
    expect(css).toContain('color: var(--acx-color-warning-border)');
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it.each([
    ['final_gpu', 'stopped', LABEL.final_gpu],
    ['provisional_cpu', 'ready', LABEL.provisional_cpu],
    [null, 'ready', LABEL.unknown],
  ] as const)(
    'statusPresentation labels parsed description_tier %s even when gpu_state is %s',
    (tier, gpuState, expected) => {
      const parsed = parsePublicDemoEnvelope(
        completedDescription({ gpu_state: gpuState, description_tier: tier }),
      );
      const presentation = statusPresentation(parsed);

      expect(parsed.description).toBe(DESCRIPTION);
      expect(presentation.state).toBe(tier === 'final_gpu' ? 'completed' : 'degraded');
      expect(presentation.message).toBe(expected);
      expect(presentation.message).not.toBe(DESCRIPTION);
      if (tier !== 'final_gpu') expect(presentation.message).not.toMatch(/description complete/i);
    },
  );

  it('statusPresentation labels a legacy completed description without description_tier as unknown', () => {
    const payload = completedDescription({ gpu_state: 'ready' });
    expect(Object.prototype.hasOwnProperty.call(payload, 'description_tier')).toBe(false);
    const presentation = statusPresentation(parsePublicDemoEnvelope(payload));

    expect(presentation.state).toBe('degraded');
    expect(presentation.message).toBe(LABEL.unknown);
    expect(presentation.message).not.toMatch(/description complete/i);
  });

  it('statusPresentation does not apply a GPU-final success label to a failed envelope', () => {
    const presentation = statusPresentation(
      parsePublicDemoEnvelope(
        running({
          status: 'failed',
          phase: 'failed',
          error: { code: 'acx_public_demo_pipeline_failed', message: 'The image could not be described.' },
        }),
      ),
    );

    expect(presentation.state).toBe('failed');
    expect(presentation.message).toBe('The image could not be described.');
    expect(presentation.message).not.toBe(LABEL.final_gpu);
  });

  it.each([
    ['final_gpu', 'stopped', LABEL.final_gpu],
    ['provisional_cpu', 'ready', LABEL.provisional_cpu],
    [null, 'ready', LABEL.unknown],
  ] as const)(
    'initializeDemo completed DOM shows %s label after submit+poll (gpu_state %s)',
    async (tier, gpuState, expected) => {
      document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES;
      const root = document.querySelectorAll<HTMLElement>('[data-acx-demo]')[0];
      const form = root.querySelector<HTMLFormElement>('form.acx-demo__form');
      const lake = document.querySelector<HTMLInputElement>('#acx-demo-media-1-41');
      const result = root.querySelector<HTMLElement>('[data-acx-demo-result]');
      const message = root.querySelector<HTMLElement>('[data-acx-demo-message]');
      const icon = root.querySelector<HTMLElement>('[data-acx-demo-icon]');
      expect(root).toBeInstanceOf(HTMLElement);
      expect(form).toBeInstanceOf(HTMLFormElement);
      expect(lake).toBeInstanceOf(HTMLInputElement);
      lake!.checked = true;

      const fetchImpl = vi.fn<typeof fetch>()
        .mockResolvedValueOnce(
          response(
            running({
              status: 'pending',
              phase: 'queued',
              deadline_seconds: 120,
              run_id: 'run-visible-1',
            }),
          ),
        )
        .mockResolvedValueOnce(
          response(
            completedDescription({
              run_id: 'run-visible-1',
              gpu_state: gpuState,
              description_tier: tier,
            }),
          ),
        );
      vi.stubGlobal('fetch', fetchImpl);

      try {
        initializeDemo(root);
        form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        await settle(() => form?.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled === false);

        expect(root.dataset.state).toBe(tier === 'final_gpu' ? 'completed' : 'degraded');
        expect(message?.textContent).toBe(expected);
        expect(message?.textContent).not.toBe(DESCRIPTION);
        expect(icon?.textContent).toBe(tier === 'final_gpu' ? '✓' : '!');
        expect(result?.hidden).toBe(false);
        expect(result?.textContent).toBe(DESCRIPTION);
        expect(document.activeElement).toBe(result);
        expect(Array.from(form?.elements ?? []).every((control) => !(control as HTMLInputElement).disabled)).toBe(true);
      } finally {
        vi.unstubAllGlobals();
        document.body.innerHTML = '';
      }
    },
  );

  it('initializeDemo completed DOM labels a legacy missing description_tier as unknown', async () => {
    document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES;
    const root = document.querySelectorAll<HTMLElement>('[data-acx-demo]')[0];
    const form = root.querySelector<HTMLFormElement>('form.acx-demo__form');
    const lake = document.querySelector<HTMLInputElement>('#acx-demo-media-1-41');
    const result = root.querySelector<HTMLElement>('[data-acx-demo-result]');
    const message = root.querySelector<HTMLElement>('[data-acx-demo-message]');
    lake!.checked = true;

    const completed = completedDescription({ run_id: 'run-visible-legacy', gpu_state: 'ready' });
    expect(Object.prototype.hasOwnProperty.call(completed, 'description_tier')).toBe(false);

    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(
        response(running({ status: 'pending', phase: 'queued', deadline_seconds: 120, run_id: 'run-visible-legacy' })),
      )
      .mockResolvedValueOnce(response(completed));
    vi.stubGlobal('fetch', fetchImpl);

    try {
      initializeDemo(root);
      form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await settle(() => form?.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled === false);

      expect(root.dataset.state).toBe('degraded');
      expect(message?.textContent).toBe(LABEL.unknown);
      expect(root.querySelector('[data-acx-demo-icon]')?.textContent).toBe('!');
      expect(result?.hidden).toBe(false);
      expect(result?.textContent).toBe(DESCRIPTION);
      expect(document.activeElement).toBe(result);
    } finally {
      vi.unstubAllGlobals();
      document.body.innerHTML = '';
    }
  });

  it('initializeDemo failed poll does not show a GPU-final success label', async () => {
    document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES;
    const root = document.querySelectorAll<HTMLElement>('[data-acx-demo]')[0];
    const form = root.querySelector<HTMLFormElement>('form.acx-demo__form');
    const lake = document.querySelector<HTMLInputElement>('#acx-demo-media-1-41');
    const result = root.querySelector<HTMLElement>('[data-acx-demo-result]');
    const message = root.querySelector<HTMLElement>('[data-acx-demo-message]');
    lake!.checked = true;

    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(
        response(running({ status: 'pending', phase: 'queued', deadline_seconds: 120, run_id: 'run-visible-fail' })),
      )
      .mockResolvedValueOnce(
        response(
          running({
            run_id: 'run-visible-fail',
            status: 'failed',
            phase: 'failed',
            error: { code: 'acx_public_demo_pipeline_failed', message: 'The image could not be described.' },
          }),
        ),
      );
    vi.stubGlobal('fetch', fetchImpl);

    try {
      initializeDemo(root);
      form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await settle(() => form?.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled === false);

      expect(root.dataset.state).toBe('failed');
      expect(message?.textContent).toBe('The image could not be described.');
      expect(message?.textContent).not.toBe(LABEL.final_gpu);
      expect(result?.hidden).toBe(true);
      expect(result?.textContent).toBe('');
    } finally {
      vi.unstubAllGlobals();
      document.body.innerHTML = '';
    }
  });
});

describe('public demo radio contract from actual PHP shortcode markup', () => {
  const chooseImageMessage = 'Choose an image before requesting a description.';
  const postBodies = (fetchImpl: ReturnType<typeof vi.fn<typeof fetch>>): Array<{ media_id: number }> =>
    fetchImpl.mock.calls
      .filter((call) => (call[1] as RequestInit | undefined)?.method === 'POST')
      .map((call) => JSON.parse(String((call[1] as RequestInit).body)) as { media_id: number });

  const settle = async (predicate: () => boolean): Promise<void> => {
    for (let tick = 0; tick < 200; tick += 1) {
      if (predicate()) return;
      await Promise.resolve();
      await new Promise((resolve) => { setTimeout(resolve, 0); });
    }
    throw new Error('timed out waiting for the demo client to settle');
  };

  const messageOf = (root: HTMLElement | undefined): string =>
    root?.querySelector('[data-acx-demo-message]')?.textContent ?? '';

  it('loads instance-scoped group names from the PHP-rendered fixture, not the simplified harness', () => {
    expect(RADIO_SOURCE_ANCHORS.expected_names).toEqual(['acx-demo-media-1', 'acx-demo-media-2']);
    expect(RADIO_SOURCE_ANCHORS.forbidden_simplified_name).toBe('acx-demo-media');
    expect(RADIO_SOURCE_ANCHORS.source_anchors.php_group_name.literal).toContain("acx-demo-media-' . $instance");
    expect(RADIO_SOURCE_ANCHORS.source_anchors.js_formdata_lookup.literal).toContain("FormData(form).get('acx-demo-media')");
    expect(ACTUAL_SHORTCODE_TWO_INSTANCES).toContain('name="acx-demo-media-1"');
    expect(ACTUAL_SHORTCODE_TWO_INSTANCES).toContain('name="acx-demo-media-2"');
    expect(ACTUAL_SHORTCODE_TWO_INSTANCES.includes('name="acx-demo-media"')).toBe(false);

    document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES;
    try {
      const names = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="radio"]')).map((input) => input.name);
      expect(names).toEqual(['acx-demo-media-1', 'acx-demo-media-1', 'acx-demo-media-2', 'acx-demo-media-2']);
      expect(document.querySelector('input[name="acx-demo-media"]')).toBeNull();
    } finally {
      document.body.innerHTML = '';
    }
  });

  it('posts each form\'s selected media_id and does not leak the other instance\'s choice', async () => {
    document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES;
    const roots = Array.from(document.querySelectorAll<HTMLElement>('[data-acx-demo]'));
    const forms = roots.map((root) => root.querySelector<HTMLFormElement>('form.acx-demo__form'));
    const firstLake = document.querySelector<HTMLInputElement>('#acx-demo-media-1-41');
    const secondPath = document.querySelector<HTMLInputElement>('#acx-demo-media-2-42');
    expect(firstLake).toBeInstanceOf(HTMLInputElement);
    expect(secondPath).toBeInstanceOf(HTMLInputElement);
    firstLake!.checked = true;
    secondPath!.checked = true;

    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue(new Error('capture POST only'));
    vi.stubGlobal('fetch', fetchImpl);

    try {
      roots.forEach((root) => initializeDemo(root));

      forms[0]?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await settle(() => postBodies(fetchImpl).length >= 1 || messageOf(roots[0]) === chooseImageMessage);
      expect(
        postBodies(fetchImpl).map((body) => body.media_id),
        'selected acx-demo-media-1 value 41 must POST media_id 41',
      ).toEqual([41]);

      await settle(() => forms[0]?.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled === false);
      forms[1]?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await settle(() => postBodies(fetchImpl).length >= 2 || messageOf(roots[1]) === chooseImageMessage);
      expect(
        postBodies(fetchImpl).map((body) => body.media_id),
        'selected acx-demo-media-2 value 42 must POST 42 without the other form\'s 41',
      ).toEqual([41, 42]);
    } finally {
      vi.unstubAllGlobals();
      document.body.innerHTML = '';
    }
  });

  it('does not POST when the submitting instance has no radio selected', async () => {
    document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES;
    const roots = Array.from(document.querySelectorAll<HTMLElement>('[data-acx-demo]'));
    const firstForm = roots[0]?.querySelector<HTMLFormElement>('form.acx-demo__form');
    const secondPath = document.querySelector<HTMLInputElement>('#acx-demo-media-2-42');
    expect(secondPath).toBeInstanceOf(HTMLInputElement);
    secondPath!.checked = true;

    const fetchImpl = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchImpl);

    try {
      roots.forEach((root) => initializeDemo(root));
      firstForm?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await settle(() => messageOf(roots[0]) === chooseImageMessage);
      expect(fetchImpl, 'empty acx-demo-media-1 selection must not POST').not.toHaveBeenCalled();
      expect(messageOf(roots[0])).toBe(chooseImageMessage);
    } finally {
      vi.unstubAllGlobals();
      document.body.innerHTML = '';
    }
  });
});

describe('public demo illustrative outcome preview', () => {
  const ILLUSTRATIVE_LABEL = 'Illustrative example — not a live result';
  const ILLUSTRATIVE_DISCLAIMER =
    'This example is not a description of your selected image. Your live result may differ.';
  const ILLUSTRATIVE_EXAMPLE = 'Alex stands beside a bicycle outside a cafe.';
  const LIVE_DESCRIPTION = 'A lakeside path.';

  const settle = async (predicate: () => boolean): Promise<void> => {
    for (let tick = 0; tick < 200; tick += 1) {
      if (predicate()) return;
      await Promise.resolve();
      await new Promise((resolve) => { setTimeout(resolve, 0); });
    }
    throw new Error('timed out waiting for the demo client to settle');
  };

  it('shows a static illustrative preview before submit in the PHP-rendered fixture', () => {
    document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES;
    try {
      const roots = Array.from(document.querySelectorAll<HTMLElement>('[data-acx-demo]'));
      expect(roots).toHaveLength(2);
      for (const root of roots) {
        const preview = root.querySelector<HTMLElement>('[data-acx-demo-preview]');
        const submit = root.querySelector<HTMLElement>('.acx-demo__submit');
        const result = root.querySelector<HTMLElement>('[data-acx-demo-result]');
        expect(preview, 'INT-07 outcome sample must exist beside input radios').toBeInstanceOf(HTMLElement);
        expect(preview?.textContent).toContain(ILLUSTRATIVE_LABEL);
        expect(preview?.textContent).toContain(ILLUSTRATIVE_DISCLAIMER);
        expect(preview?.textContent).toContain(ILLUSTRATIVE_EXAMPLE);
        expect(preview?.getAttribute('role')).not.toBe('status');
        expect(preview?.getAttribute('aria-live')).toBeNull();
        expect(submit).toBeInstanceOf(HTMLElement);
        expect(
          preview!.compareDocumentPosition(submit!) & Node.DOCUMENT_POSITION_FOLLOWING,
          'illustrative preview must precede expensive submit',
        ).toBeTruthy();
        expect(result?.hidden).toBe(true);
        expect(result?.textContent).toBe('');
        expect(result?.contains(preview)).toBe(false);
      }
    } finally {
      document.body.innerHTML = '';
    }
  });

  it('initializeDemo and image selection do not POST; explicit submit still fills the live result', async () => {
    document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES;
    const root = document.querySelectorAll<HTMLElement>('[data-acx-demo]')[0];
    const form = root.querySelector<HTMLFormElement>('form.acx-demo__form');
    const lake = document.querySelector<HTMLInputElement>('#acx-demo-media-1-41');
    const result = root.querySelector<HTMLElement>('[data-acx-demo-result]');
    lake!.checked = true;

    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(
        response(running({ status: 'pending', phase: 'queued', deadline_seconds: 120, run_id: 'run-preview-1' })),
      )
      .mockResolvedValueOnce(
        response(
          running({
            run_id: 'run-preview-1',
            status: 'completed',
            phase: 'complete',
            progress: { done: 1, total: 1 },
            description: LIVE_DESCRIPTION,
            description_tier: 'final_gpu',
            gpu_state: 'ready',
          }),
        ),
      );
    vi.stubGlobal('fetch', fetchImpl);

    try {
      initializeDemo(root);
      expect(fetchImpl, 'initializeDemo must not POST').not.toHaveBeenCalled();
      lake?.dispatchEvent(new Event('change', { bubbles: true }));
      lake?.dispatchEvent(new Event('input', { bubbles: true }));
      expect(fetchImpl, 'selecting an image must not POST').not.toHaveBeenCalled();
      expect(result?.hidden).toBe(true);
      expect(result?.textContent).toBe('');

      form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await settle(() => form?.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled === false);

      expect(fetchImpl.mock.calls.some((call) => (call[1] as RequestInit | undefined)?.method === 'POST')).toBe(true);
      expect(result?.hidden).toBe(false);
      expect(result?.textContent).toBe(LIVE_DESCRIPTION);
      expect(result?.textContent).not.toBe(ILLUSTRATIVE_EXAMPLE);
      expect(root.querySelector('[data-acx-demo-message]')?.textContent).toBe('GPU description complete.');
      const preview = root.querySelector<HTMLElement>('[data-acx-demo-preview]');
      expect(preview, 'illustrative preview must remain after the live result lands').toBeInstanceOf(HTMLElement);
      expect(preview?.textContent).toContain(ILLUSTRATIVE_EXAMPLE);
      expect(preview?.textContent).not.toContain(LIVE_DESCRIPTION);
    } finally {
      vi.unstubAllGlobals();
      document.body.innerHTML = '';
    }
  });
});

// Real shortcode DOM and public controller envelopes, including terminal replay.
const mountRetryDemo = () => {
  document.body.innerHTML = ACTUAL_SHORTCODE_TWO_INSTANCES.split('\n')[0];
  const root = document.querySelector<HTMLElement>('[data-acx-demo]');
  const form = root?.querySelector<HTMLFormElement>('form.acx-demo__form');
  const radio = form?.querySelector<HTMLInputElement>('input[value="41"]');
  const submitButton = form?.querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!root || !form || !radio || !submitButton) throw new Error('Missing actual shortcode controls');
  radio.checked = true;
  initializeDemo(root);
  return {
    root, form, submitButton,
    stop: () => root.querySelector<HTMLButtonElement>('.acx-demo__stop'),
    submit: () => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })),
    message: () => root.querySelector('[data-acx-demo-message]')?.textContent,
  };
};
const submittedRun = () => response(running({ status: 'pending', phase: 'queued', gpu_state: 'stopped', deadline_seconds: 690 }));
const completedRun = () => response(running({ status: 'completed', phase: 'complete', progress: { done: 1, total: 1 }, description: 'A lakeside path.', description_tier: 'final_gpu' }));
const postedKey = (fetchImpl: ReturnType<typeof vi.fn<typeof fetch>>, index: number): string => {
  const body = fetchImpl.mock.calls[index]?.[1]?.body;
  expect(body, `POST #${index} must have a retry key`).toBeDefined();
  return JSON.parse(String(body)).idempotency_key;
};

describe('Stop waiting', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('is secondary and hidden at rest, aborts a pending poll, restores focus and re-attaches on restart', async () => {
    let finishOldPoll: ((response: Response) => void) | undefined;
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(submittedRun())
      // Ignore abort to prove that a late response cannot overwrite stopped/restarted UI.
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOldPoll = resolve; }))
      .mockResolvedValueOnce(submittedRun())
      .mockResolvedValueOnce(completedRun());
    vi.stubGlobal('fetch', fetchImpl);
    const demo = mountRetryDemo();
    expect(demo.stop()?.hidden).toBe(true);
    expect(demo.stop()?.type).toBe('button');
    expect(demo.form.contains(demo.stop())).toBe(false);
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(demo.stop()?.hidden).toBe(false);
    demo.stop()?.focus();
    demo.stop()?.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl.mock.calls[1]?.[1]?.signal?.aborted).toBe(true);
    expect(demo.root.dataset.state).toBe('stopped');
    expect(demo.message()).toBe(STOPPED_COPY);
    expect(demo.root.querySelector('[data-acx-demo-icon]')?.textContent).toBe('■');
    expect(demo.root.querySelector('[data-acx-demo-status]')?.getAttribute('role')).toBe('status');
    expect(demo.stop()?.hidden).toBe(true);
    expect(demo.submitButton.disabled).toBe(false);
    expect(document.activeElement).toBe(demo.submitButton);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(postedKey(fetchImpl, 2)).toBe(postedKey(fetchImpl, 0));
    expect(new Headers(fetchImpl.mock.calls[3]?.[1]?.headers).get('Idempotency-Key')).toBe(postedKey(fetchImpl, 0));
    expect(demo.root.dataset.state).toBe('completed');
    expect(demo.stop()?.hidden).toBe(true);
    finishOldPoll?.(response(running({ phase: 'warming' })));
    await vi.advanceTimersByTimeAsync(120_000);
    expect(demo.root.dataset.state).toBe('completed');
    expect(fetchImpl).toHaveBeenCalledTimes(4);
  });

  it('stops backoff without another request and supports repeated stop/restart cycles', async () => {
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(submittedRun()).mockResolvedValueOnce(response(running({ phase: 'warming' })))
      .mockResolvedValueOnce(submittedRun()).mockResolvedValueOnce(response(running()));
    vi.stubGlobal('fetch', fetchImpl);
    const demo = mountRetryDemo();
    for (const expectedCalls of [2, 4]) {
      demo.submit();
      await vi.advanceTimersByTimeAsync(0);
      expect(demo.stop()?.hidden).toBe(false);
      demo.stop()?.click();
      await vi.advanceTimersByTimeAsync(10_000);
      expect(demo.root.dataset.state).toBe('stopped');
      expect(fetchImpl).toHaveBeenCalledTimes(expectedCalls);
    }
    expect(postedKey(fetchImpl, 2)).toBe(postedKey(fetchImpl, 0));
  });

  it.each(['fetch', 'body'] as const)('can stop during submit %s and keeps the same key despite uncertain acceptance', async (stage) => {
    const pending = new Promise<Response>(() => {});
    const fetchImpl = vi.fn<typeof fetch>();
    if (stage === 'fetch') fetchImpl.mockReturnValueOnce(pending);
    else {
      const slowBody = submittedRun();
      vi.spyOn(slowBody, 'json').mockImplementation(() => new Promise(() => {}));
      fetchImpl.mockResolvedValueOnce(slowBody);
    }
    fetchImpl.mockResolvedValueOnce(submittedRun()).mockResolvedValueOnce(completedRun());
    vi.stubGlobal('fetch', fetchImpl);
    const demo = mountRetryDemo();
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(demo.stop()?.hidden).toBe(false);
    demo.stop()?.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    expect(demo.root.dataset.state).toBe('stopped');
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(postedKey(fetchImpl, 1)).toBe(postedKey(fetchImpl, 0));
    expect(demo.root.dataset.state).toBe('completed');
  });
});

describe('retry key lifecycle', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('keeps the key at the 120s ceiling and aborts the local poll', async () => {
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(submittedRun())
      .mockImplementationOnce(() => new Promise<Response>(() => {}))
      .mockResolvedValueOnce(submittedRun()).mockResolvedValueOnce(completedRun());
    vi.stubGlobal('fetch', fetchImpl);
    const demo = mountRetryDemo();
    demo.submit();
    await vi.advanceTimersByTimeAsync(119_999);
    expect(demo.submitButton.disabled).toBe(true);
    await vi.advanceTimersByTimeAsync(1);
    expect(demo.message()).toBe(TIMEOUT_COPY);
    expect(fetchImpl.mock.calls[1]?.[1]?.signal?.aborted).toBe(true);
    expect(demo.submitButton.disabled).toBe(false);
    expect(demo.stop()?.hidden).toBe(true);
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(postedKey(fetchImpl, 2)).toBe(postedKey(fetchImpl, 0));
  });

  // Shapes from PublicDemoDescribeController::public_envelope_response/status.
  it.each([
    ['failed', () => response(running({ status: 'failed', phase: 'failed', error: { code: 'acx_public_demo_pipeline_failed', message: 'The image could not be described. Please try again later.' } }))],
    ['cancelled', () => response(running({ status: 'cancelled', phase: 'cancelled', error: { code: 'acx_public_demo_pipeline_failed', message: 'The image could not be described. Please try again later.' } }))],
    ['completed_with_errors', () => response(running({ status: 'completed_with_errors', phase: 'complete', progress: { done: 1, total: 1 }, error: { code: 'acx_public_demo_partial_failure', message: 'The description did not complete successfully. Please try another image.' } }))],
    ['completed without description', () => response(running({ status: 'completed', phase: 'complete', progress: { done: 1, total: 1 } }))],
    ['run unavailable', () => response({ code: 'acx_public_demo_run_not_available', message: 'That public demo run is not available.', data: { status: 403 } }, 403)],
  ] as const)('retires the key after %s', async (_label, terminalResponse) => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValueOnce(submittedRun())
      .mockResolvedValueOnce(terminalResponse()).mockResolvedValueOnce(submittedRun()).mockResolvedValueOnce(completedRun());
    vi.stubGlobal('fetch', fetchImpl);
    const demo = mountRetryDemo();
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(demo.root.dataset.state).toBe('failed');
    expect(demo.submitButton.disabled).toBe(false);
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(postedKey(fetchImpl, 2)).not.toBe(postedKey(fetchImpl, 0));
  });

  it.each([
    ['network', () => Promise.reject(new TypeError('Network unavailable'))],
    ['invalid envelope', () => Promise.resolve(response({ status: 'running' }))],
    ['rate limit', () => Promise.resolve(response({ code: 'acx_public_demo_rate_limited', message: 'Please retry.', data: { status: 429 } }, 429))],
    ['server busy', () => Promise.resolve(response({ code: 'acx_public_demo_state_unavailable', message: 'Please retry.', data: { status: 503 } }, 503))],
    ['nonce forbidden', () => Promise.resolve(response({ code: 'rest_cookie_invalid_nonce', message: 'Invalid nonce.', data: { status: 403 } }, 403))],
    ['unavailable code without 403', () => Promise.resolve(response({ code: 'acx_public_demo_run_not_available', message: 'Please retry.', data: { status: 503 } }, 503))],
  ] as const)('preserves the key after transient %s', async (_label, failure) => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValueOnce(submittedRun())
      .mockImplementationOnce(failure).mockResolvedValueOnce(submittedRun()).mockResolvedValueOnce(completedRun());
    vi.stubGlobal('fetch', fetchImpl);
    const demo = mountRetryDemo();
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(demo.submitButton.disabled).toBe(false);
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(postedKey(fetchImpl, 2)).toBe(postedKey(fetchImpl, 0));
  });

  it('keeps navigation abort distinct from Stop waiting and retains the key', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValueOnce(submittedRun())
      .mockImplementationOnce(() => new Promise<Response>(() => {}))
      .mockResolvedValueOnce(submittedRun()).mockResolvedValueOnce(completedRun());
    vi.stubGlobal('fetch', fetchImpl);
    const demo = mountRetryDemo();
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    globalThis.dispatchEvent(new Event('pagehide'));
    await vi.advanceTimersByTimeAsync(0);
    expect(demo.root.dataset.state).toBe('failed');
    expect(demo.message()).toBe('The demo request was stopped because the page is closing.');
    expect(fetchImpl.mock.calls[1]?.[1]?.signal?.aborted).toBe(true);
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(postedKey(fetchImpl, 2)).toBe(postedKey(fetchImpl, 0));
  });

  it('mints a new key when the visitor chooses another image after Stop', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValueOnce(submittedRun())
      .mockImplementationOnce(() => new Promise<Response>(() => {}))
      .mockResolvedValueOnce(submittedRun()).mockResolvedValueOnce(completedRun());
    vi.stubGlobal('fetch', fetchImpl);
    const demo = mountRetryDemo();
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    demo.stop()?.click();
    await vi.advanceTimersByTimeAsync(0);
    const other = demo.form.querySelector<HTMLInputElement>('input[value="42"]');
    if (!other) throw new Error('Missing second image');
    other.checked = true;
    demo.submit();
    await vi.advanceTimersByTimeAsync(0);
    expect(postedKey(fetchImpl, 2)).not.toBe(postedKey(fetchImpl, 0));
  });
});

describe('demo copy is translatable', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses call-time gettext and the alt-context domain for status labels', () => {
    const translate = vi.fn((text: string) => `«${text}»`);
    vi.stubGlobal('wp', { i18n: { __: translate, sprintf: (format: string, value: string) => format.replace('%s', value) } });
    expect(statusPresentation(parsePublicDemoEnvelope(running({ phase: 'warming' }))).message).toBe(`«${COLD_START_COPY}»`);
    for (const payload of [
      running({ phase: 'queued', status: 'pending' }),
      running({ progress: { done: 0, total: 0 } }),
      running({ status: 'completed', phase: 'complete', description: 'Draft.', description_tier: 'provisional_cpu' }),
      running({ status: 'completed', phase: 'complete', description: 'Draft.', description_tier: null }),
    ]) expect(statusPresentation(parsePublicDemoEnvelope(payload)).message).toMatch(/^«.*»$/);
    expect(translate.mock.calls.every((call) => Reflect.get(call, '1') === 'alt-context')).toBe(true);
  });

  it('formats percentages with the page language before translation interpolation', () => {
    const previousLang = document.documentElement.lang;
    vi.stubGlobal('wp', { i18n: { __: (text: string) => `«${text}»`, sprintf: (format: string, value: string) => format.replace('%s', value) } });
    try {
      document.documentElement.lang = 'fr-FR';
      const message = statusPresentation(parsePublicDemoEnvelope(running({ progress: { done: 1, total: 2 } }))).message;
      expect(message).toBe(`«Describing the image… ${new Intl.NumberFormat('fr-FR', { style: 'percent', maximumFractionDigits: 0 }).format(0.5)}»`);
      expect(message).not.toContain('50%');
    } finally {
      document.documentElement.lang = previousLang;
    }
  });
});
