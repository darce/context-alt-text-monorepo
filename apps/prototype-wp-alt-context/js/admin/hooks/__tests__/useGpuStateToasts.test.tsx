import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { __, _n } from '@wordpress/i18n';

import { GPU_STATE } from '../../api/describeApi';
import type { ToastOptions } from '../../context/ToastContext';
import { GPU_STATE_VOCABULARY } from '../../pages/workbench/gpuStatePresentation';
import { setActiveDescribeRunId, setDescribeProgressMounted } from '../activeDescribeRun';
import {
  ACTIVITY_KIND,
  ACTIVITY_REASON,
  type ActivityKind,
  type ActivityStatus,
  type ActivityStatusActions,
  type UseActivityStatusResult,
} from '../useActivityStatus';
import { useGpuStateToasts } from '../useGpuStateToasts';

const infoMock = vi.fn<(message: string, options?: ToastOptions) => void>();
const errorMock = vi.fn<(message: string, options?: ToastOptions) => void>();
const successMock = vi.fn<(message: string, options?: ToastOptions) => void>();

const useActivityStatusMock = vi.hoisted(() => vi.fn());

vi.mock('../../context/ToastContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../context/ToastContext')>();
  return {
    ...actual,
    useToast: () => ({
      toast: vi.fn(),
      success: successMock,
      info: infoMock,
      error: errorMock,
    }),
  };
});

vi.mock('../useActivityStatus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../useActivityStatus')>();
  return {
    ...actual,
    useActivityStatus: (...args: unknown[]) => useActivityStatusMock(...args),
  };
});

vi.mock('@wordpress/i18n', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@wordpress/i18n')>();
  return { ...actual, _n: vi.fn(actual._n) };
});

const idleStatus = (overrides: Partial<ActivityStatus> = {}): ActivityStatus => ({
  kind: ACTIVITY_KIND.IDLE,
  progress: null,
  etaSeconds: null,
  reason: null,
  canCancel: false,
  runId: null,
  gpuState: GPU_STATE.STOPPED,
  retryable: false,
  draftCount: 0,
  ...overrides,
});

const idleActions = (overrides: Partial<ActivityStatusActions> = {}): ActivityStatusActions => ({
  onCancel: null,
  onRetry: null,
  reviewDraftsHref: null,
  backToRunHref: null,
  ...overrides,
});

const hookResult = (overrides: Partial<UseActivityStatusResult> = {}): UseActivityStatusResult => ({
  status: idleStatus(),
  actions: idleActions(),
  isCancelling: false,
  ...overrides,
});

const LocationProbe = (): React.JSX.Element => {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
};

const ToastHarness = (): React.JSX.Element => {
  useGpuStateToasts();
  return <LocationProbe />;
};

const harnessTree = (): React.JSX.Element => (
  <MemoryRouter initialEntries={['/people']}>
    <ToastHarness />
  </MemoryRouter>
);

const renderHarness = () => render(harnessTree());

const observeSequence = (
  results: readonly UseActivityStatusResult[],
  options: { mounted?: boolean } = {},
): ReturnType<typeof render> => {
  if (results[0] === undefined) {
    throw new Error('Scripted activity sequence must not be empty');
  }
  setDescribeProgressMounted(options.mounted ?? false);
  useActivityStatusMock.mockReturnValue(results[0]);
  const view = renderHarness();
  for (const next of results.slice(1)) {
    useActivityStatusMock.mockReturnValue(next);
    view.rerender(harnessTree());
  }
  return view;
};

const expectNoToasts = (): void => {
  expect(infoMock).not.toHaveBeenCalled();
  expect(errorMock).not.toHaveBeenCalled();
  expect(successMock).not.toHaveBeenCalled();
};

const expectOnlyInfoToast = (message: string): ToastOptions | undefined => {
  expect(infoMock).toHaveBeenCalledOnce();
  expect(infoMock.mock.calls[0]?.[0]).toBe(message);
  expect(errorMock).not.toHaveBeenCalled();
  expect(successMock).not.toHaveBeenCalled();
  return infoMock.mock.calls[0]?.[1];
};

const expectOnlySuccessToast = (message: string): ToastOptions | undefined => {
  expect(successMock).toHaveBeenCalledOnce();
  expect(successMock.mock.calls[0]?.[0]).toBe(message);
  expect(infoMock).not.toHaveBeenCalled();
  expect(errorMock).not.toHaveBeenCalled();
  return successMock.mock.calls[0]?.[1];
};

const requireToastOptions = (options: ToastOptions | undefined): ToastOptions => {
  if (!options) {
    throw new Error('Expected the toast to include options');
  }
  return options;
};

const expectOnlyErrorToast = (message: string): ToastOptions => {
  expect(errorMock).toHaveBeenCalledOnce();
  expect(errorMock.mock.calls[0]?.[0]).toBe(message);
  expect(infoMock).not.toHaveBeenCalled();
  expect(successMock).not.toHaveBeenCalled();
  const options = errorMock.mock.calls[0]?.[1];
  if (!options) {
    throw new Error('Expected the error toast to include options');
  }
  return options;
};

const runStatus = (
  kind: ActivityKind,
  overrides: Partial<ActivityStatus> = {},
): ActivityStatus =>
  idleStatus({
    kind,
    runId: 'run-1',
    gpuState: GPU_STATE.READY,
    ...overrides,
  });

describe('useGpuStateToasts edge policy', () => {
  let originalLang: string | null;
  let originalFormatDescriptor: PropertyDescriptor | undefined;
  beforeEach(() => {
    vi.clearAllMocks();
    originalLang = document.documentElement.getAttribute('lang');
    originalFormatDescriptor = Object.getOwnPropertyDescriptor(Intl.NumberFormat.prototype, 'format');
    document.documentElement.lang = 'en-US';
    vi.mocked(_n).mockImplementation((single, plural, count) => count === 1 ? __(single, 'alt-context') : __(plural, 'alt-context'));
    useActivityStatusMock.mockReturnValue(hookResult());
    act(() => {
      setActiveDescribeRunId(null);
      setDescribeProgressMounted(false);
    });
  });

  afterEach(() => {
    act(() => {
      setActiveDescribeRunId(null);
      setDescribeProgressMounted(false);
    });
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    if (originalFormatDescriptor) Object.defineProperty(Intl.NumberFormat.prototype, 'format', originalFormatDescriptor);
    if (originalLang === null) document.documentElement.removeAttribute('lang');
    else document.documentElement.lang = originalLang;
  });

  it('reads useActivityStatus as the sole activity-status authority', () => {
    renderHarness();
    expect(useActivityStatusMock).toHaveBeenCalled();
  });

  it('toasts warming on a kind-change to warming away from progress', () => {
    observeSequence([
      hookResult({ status: runStatus(ACTIVITY_KIND.IDLE, { gpuState: GPU_STATE.STOPPED }) }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.WARMING, { gpuState: GPU_STATE.WARMING, canCancel: true }),
      }),
    ]);
    expect(expectOnlyInfoToast(GPU_STATE_VOCABULARY.warmingToast)).toBeUndefined();
  });

  it('toasts warming to describing as GPU ready with Back to run', () => {
    const view = observeSequence([
      hookResult({
        status: runStatus(ACTIVITY_KIND.WARMING, { gpuState: GPU_STATE.WARMING, canCancel: true }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, { gpuState: GPU_STATE.READY, canCancel: true }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
    ]);

    const options = requireToastOptions(expectOnlyInfoToast(GPU_STATE_VOCABULARY.readyToast));
    expect(options.action).toMatchObject({
      label: GPU_STATE_VOCABULARY.backToRun,
      altText: GPU_STATE_VOCABULARY.backToRunAltText,
    });
    expect(options.durationMs).toBeNull();
    act(() => options.action?.onClick());
    expect(view.getByTestId('location')).toHaveTextContent('/workbench');
  });

  it('toasts describing to done with Review N drafts into the review queue', () => {
    const view = observeSequence([
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.DONE, { draftCount: 4 }),
        actions: idleActions({ reviewDraftsHref: '#/description-history?run=run-1' }),
      }),
    ]);

    const options = requireToastOptions(
      expectOnlySuccessToast(GPU_STATE_VOCABULARY.doneToast(4)),
    );
    expect(options.action).toMatchObject({
      label: GPU_STATE_VOCABULARY.reviewDrafts(4),
      altText: GPU_STATE_VOCABULARY.reviewDraftsAltText,
    });
    expect(options.durationMs).toBeNull();
    act(() => options.action?.onClick());
    expect(view.getByTestId('location')).toHaveTextContent('/description-history?run=run-1');
  });

  it('toasts failed warmup timeout with Retry when C2 marks it retryable', () => {
    const onRetry = vi.fn();
    observeSequence([
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.FAILED, {
          reason: ACTIVITY_REASON.GPU_WARMUP_TIMEOUT,
          retryable: true,
          gpuState: GPU_STATE.STOPPED,
        }),
        actions: idleActions({ onRetry }),
      }),
    ]);

    const options = expectOnlyErrorToast(GPU_STATE_VOCABULARY.failedToastWarmupTimeout);
    expect(options.action).toMatchObject({
      label: GPU_STATE_VOCABULARY.retry,
      altText: GPU_STATE_VOCABULARY.retryAltText,
    });
    expect(options.durationMs).toBeNull();
    act(() => options.action?.onClick());
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it.each([
    [ACTIVITY_REASON.DESCRIBE_POLL_ERROR, GPU_STATE_VOCABULARY.failedToastDescribePoll, true],
    [ACTIVITY_REASON.SCAN_FAILED, GPU_STATE_VOCABULARY.failedToastScanFailed, true],
    [ACTIVITY_REASON.FAILED, GPU_STATE_VOCABULARY.failedToastFailed, false],
    [ACTIVITY_REASON.CANCELLED, GPU_STATE_VOCABULARY.failedToastCancelled, false],
  ] as const)('toasts failed reason %s with retryable=%s', (reason, message, retryable) => {
    const onRetry = vi.fn();
    observeSequence([
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true }) }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.FAILED, { reason, retryable }),
        actions: idleActions({ onRetry: retryable ? onRetry : null }),
      }),
    ]);
    const options = expectOnlyErrorToast(message);
    expect(options.durationMs).toBeNull();
    if (retryable) {
      expect(options.action).toMatchObject({
        label: GPU_STATE_VOCABULARY.retry,
        altText: GPU_STATE_VOCABULARY.retryAltText,
      });
    } else {
      expect(options.action).toBeUndefined();
    }
  });

  it('does not toast a GPU status poll failure with no active run', () => {
    observeSequence([
      hookResult({ status: idleStatus() }),
      hookResult({
        status: idleStatus({
          kind: ACTIVITY_KIND.FAILED,
          reason: ACTIVITY_REASON.GPU_STATUS_UNAVAILABLE,
          runId: null,
          retryable: true,
        }),
      }),
    ]);

    expectNoToasts();
  });

  it('toasts a GPU status poll failure when an active run has failed', () => {
    observeSequence([
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true }) }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.FAILED, {
          reason: ACTIVITY_REASON.GPU_STATUS_UNAVAILABLE,
          retryable: true,
        }),
      }),
    ]);

    const options = expectOnlyErrorToast(GPU_STATE_VOCABULARY.failedToastGpuUnavailable);
    expect(options.durationMs).toBeNull();
  });

  it('toasts unknown failed reasons with generic copy and no Retry', () => {
    observeSequence([
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true }) }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.FAILED, { reason: 'mystery_code', retryable: false }),
      }),
    ]);
    const options = expectOnlyErrorToast(GPU_STATE_VOCABULARY.failedToastWithReason('mystery_code'));
    expect(options.action).toBeUndefined();
  });

  it.each([GPU_STATE.STOPPED, GPU_STATE.STARTING, GPU_STATE.WARMING, GPU_STATE.READY])(
    'always toasts %s to degraded with Review results even while mounted',
    (previous) => {
      observeSequence(
        [
          hookResult({
            status: runStatus(ACTIVITY_KIND.DESCRIBING, { gpuState: previous, canCancel: true }),
          }),
          hookResult({
            status: runStatus(ACTIVITY_KIND.DESCRIBING, {
              gpuState: GPU_STATE.DEGRADED,
              draftCount: 1,
              canCancel: true,
            }),
          }),
        ],
        { mounted: true },
      );
      const options = expectOnlyErrorToast(GPU_STATE_VOCABULARY.degradedToastWithDrafts(1, 'en-US'));
      expect(options.action).toMatchObject({
        label: GPU_STATE_VOCABULARY.reviewResults,
        altText: GPU_STATE_VOCABULARY.reviewResultsAltText,
      });
      expect(options.durationMs).toBeNull();
    },
  );

  it('never toasts an unknown GPU state into degraded', () => {
    observeSequence([
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, { gpuState: GPU_STATE.UNKNOWN, canCancel: true }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, {
          gpuState: GPU_STATE.DEGRADED,
          canCancel: true,
        }),
      }),
    ]);
    expectNoToasts();
  });

  it('never toasts repeated kind polls', () => {
    observeSequence([
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true }) }),
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true, progress: 0.4 }) }),
    ]);
    expectNoToasts();
  });

  it.each([
    [
      hookResult({ status: runStatus(ACTIVITY_KIND.IDLE, { gpuState: GPU_STATE.STOPPED }) }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.WARMING, { gpuState: GPU_STATE.WARMING, canCancel: true }),
      }),
    ],
    [
      hookResult({
        status: runStatus(ACTIVITY_KIND.WARMING, { gpuState: GPU_STATE.WARMING, canCancel: true }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, { gpuState: GPU_STATE.READY, canCancel: true }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
    ],
    [
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true }) }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.DONE, { draftCount: 2 }),
        actions: idleActions({ reviewDraftsHref: '#/description-history?run=run-1' }),
      }),
    ],
    [
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { canCancel: true }) }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.FAILED, {
          reason: ACTIVITY_REASON.FAILED,
          retryable: false,
        }),
      }),
    ],
  ])('suppresses kind-change edges while progress is mounted', (previous, next) => {
    observeSequence([previous, next], { mounted: true });
    expectNoToasts();
  });

  it.each(Object.values(ACTIVITY_KIND))('does not toast first observation %s', (kind) => {
    observeSequence([hookResult({ status: runStatus(kind) })]);
    expectNoToasts();
  });

  it('does not toast a scanning kind-change', () => {
    observeSequence([
      hookResult({ status: idleStatus() }),
      hookResult({
        status: idleStatus({
          kind: ACTIVITY_KIND.SCANNING,
          progress: 0.2,
          canCancel: true,
        }),
      }),
    ]);
    expectNoToasts();
  });

  it('emits the same kind edge at most once for a run id', () => {
    observeSequence([
      hookResult({ status: runStatus(ACTIVITY_KIND.IDLE, { gpuState: GPU_STATE.STOPPED }) }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.WARMING, { gpuState: GPU_STATE.WARMING, canCancel: true }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, { gpuState: GPU_STATE.READY, canCancel: true }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.WARMING, { gpuState: GPU_STATE.WARMING, canCancel: true }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, { gpuState: GPU_STATE.READY, canCancel: true }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
    ]);
    expect(infoMock).toHaveBeenCalledTimes(2);
    expect(infoMock.mock.calls[0]?.[0]).toBe(GPU_STATE_VOCABULARY.warmingToast);
    expect(infoMock.mock.calls[1]?.[0]).toBe(GPU_STATE_VOCABULARY.readyToast);
  });

  it('re-arms edge memory for a new run id', () => {
    const view = observeSequence([
      hookResult({
        status: runStatus(ACTIVITY_KIND.WARMING, { gpuState: GPU_STATE.WARMING, canCancel: true }),
      }),
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, { gpuState: GPU_STATE.READY, canCancel: true }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
    ]);
    expect(infoMock).toHaveBeenCalledOnce();

    useActivityStatusMock.mockReturnValue(
      hookResult({
        status: runStatus(ACTIVITY_KIND.WARMING, {
          runId: 'run-2',
          gpuState: GPU_STATE.WARMING,
          canCancel: true,
        }),
      }),
    );
    view.rerender(harnessTree());
    expect(infoMock).toHaveBeenCalledOnce();

    useActivityStatusMock.mockReturnValue(
      hookResult({
        status: runStatus(ACTIVITY_KIND.DESCRIBING, {
          runId: 'run-2',
          gpuState: GPU_STATE.READY,
          canCancel: true,
        }),
        actions: idleActions({ backToRunHref: '#/workbench' }),
      }),
    );
    view.rerender(harnessTree());
    expect(infoMock).toHaveBeenCalledTimes(2);
  });
  describe('UXREC-1 GPU toast evidence', () => {
    const degrade = (draftCount: number): ReturnType<typeof render> => observeSequence([
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING) }),
      hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { gpuState: GPU_STATE.DEGRADED, draftCount }) }),
    ]);

    it('warming toast makes no CPU draft claim', () => {
      observeSequence([
        hookResult({ status: runStatus(ACTIVITY_KIND.IDLE) }),
        hookResult({ status: runStatus(ACTIVITY_KIND.WARMING, { gpuState: GPU_STATE.WARMING }) }),
      ]);
      expectOnlyInfoToast('GPU warming — this run is waiting for the description service');
      expect(infoMock.mock.calls[0]?.[0]).not.toMatch(/CPU/);
    });

    it('degraded toast without returned drafts offers no review', () => {
      const view = degrade(0);
      const options = expectOnlyErrorToast('GPU unavailable — no descriptions returned yet');
      expect(options.action).toBeUndefined();
      expect(options.durationMs).toBeNull();
      expect(view.getByTestId('location')).toHaveTextContent('/people');
    });

    it('degraded toast with returned drafts names the count and keeps Review results', () => {
      const view = degrade(2);
      const options = expectOnlyErrorToast('GPU unavailable — 2 drafts ready to review');
      expect(options.action).toMatchObject({ label: 'Review results', altText: GPU_STATE_VOCABULARY.reviewResultsAltText });
      expect(options.durationMs).toBeNull();
      act(() => options.action?.onClick());
      expect(view.getByTestId('location')).toHaveTextContent('/workbench');
    });

    it.each(['en-US', 'ar-EG'])('new degraded count follows host locale %s and numeric plural selection', (locale) => {
      expect(Intl.NumberFormat.supportedLocalesOf([locale])).toEqual([locale]);
      const formatter = new Intl.NumberFormat(locale, { style: 'decimal', maximumFractionDigits: 0 });
      if (locale === 'ar-EG') expect(formatter.format(2)).not.toBe('2');
      document.documentElement.lang = locale;
      for (const count of [1, 2, 22, 1234]) {
        const expected = `GPU unavailable — ${formatter.format(count)} ${count === 1 ? 'draft' : 'drafts'} ready to review`;
        const view = degrade(count);
        const options = expectOnlyErrorToast(expected);
        expect(options.action?.label).toBe('Review results');
        expect(view.getByTestId('location')).toHaveTextContent('/people');
        expect(GPU_STATE_VOCABULARY.degradedToastWithDrafts(count, locale)).toBe(expected);
        expect(_n).toHaveBeenCalledWith('GPU unavailable — %s draft ready to review', 'GPU unavailable — %s drafts ready to review', count, 'alt-context');
        view.unmount();
        vi.clearAllMocks();
      }
    });

    it.each([null, '', '   ', 'en_US', 'not_a_locale'])('neutral raw fallback for host locale %s never uses the browser default', (locale) => {
      vi.spyOn(window.navigator, 'language', 'get').mockReturnValue('ar-EG');
      if (locale === null) document.documentElement.removeAttribute('lang');
      else document.documentElement.lang = locale;
      const constructor = vi.spyOn(Intl, 'NumberFormat');
      degrade(1234);
      expectOnlyErrorToast('GPU unavailable — 1234 drafts ready to review');
      expect(constructor).not.toHaveBeenCalled();
      expect(GPU_STATE_VOCABULARY.degradedToastWithDrafts(1234, locale)).toBe('GPU unavailable — 1234 drafts ready to review');
      expect(constructor).not.toHaveBeenCalled();
    });

    it('valid but unsupported locale never constructs a default formatter', () => {
      document.documentElement.lang = 'zz-ZZ';
      const support = vi.spyOn(Intl.NumberFormat, 'supportedLocalesOf').mockReturnValue([]);
      const constructor = vi.spyOn(Intl, 'NumberFormat');
      degrade(1234);
      expectOnlyErrorToast('GPU unavailable — 1234 drafts ready to review');
      expect(support).toHaveBeenCalledWith(['zz-ZZ'], { localeMatcher: 'lookup' });
      expect(constructor).not.toHaveBeenCalled();
    });

    it.each(['canonical', 'support', 'constructor', 'format', 'Intl'])('missing Intl API %s gives neutral raw fallback', (api) => {
      if (api === 'canonical') vi.stubGlobal('Intl', { ...Intl, NumberFormat: Intl.NumberFormat, getCanonicalLocales: undefined });
      if (api === 'support') vi.spyOn(Intl.NumberFormat, 'supportedLocalesOf').mockImplementation(() => { throw new Error('unavailable'); });
      if (api === 'constructor') vi.spyOn(Intl, 'NumberFormat').mockImplementation(() => { throw new Error('unavailable'); });
      if (api === 'format') Object.defineProperty(Intl.NumberFormat.prototype, 'format', { configurable: true, get: () => () => { throw new Error('unavailable'); } });
      if (api === 'Intl') vi.stubGlobal('Intl', undefined);
      degrade(1234);
      const options = expectOnlyErrorToast('GPU unavailable — 1234 drafts ready to review');
      expect(options.action?.label).toBe('Review results');
    });

    it('host lang read failure gives neutral raw fallback', () => {
      vi.spyOn(document.documentElement, 'lang', 'get').mockImplementation(() => { throw new Error('unavailable'); });
      degrade(1234);
      expectOnlyErrorToast('GPU unavailable — 1234 drafts ready to review');
    });

    it.each([1, 2, 22, 5, 11])('Polish catalog selects with raw numeric N=%s and both literal messages', (count) => {
      document.documentElement.lang = 'pl-PL';
      vi.mocked(_n).mockImplementation((_single, _plural, n) => n === 1 ? __('one:%s', 'alt-context') : n === 2 || n === 22 ? __('few:%s', 'alt-context') : __('many:%s', 'alt-context'));
      degrade(count);
      const category = count === 1 ? 'one' : count === 2 || count === 22 ? 'few' : 'many';
      expectOnlyErrorToast(`${category}:${new Intl.NumberFormat('pl-PL').format(count)}`);
      expect(_n).toHaveBeenCalledWith('GPU unavailable — %s draft ready to review', 'GPU unavailable — %s drafts ready to review', count, 'alt-context');
    });

    it.each([null, '#/workbench?hasDraft=1&run=stale'])('DONE zero returned drafts has neutral completion copy and no review action (%s)', (href) => {
      const view = observeSequence([
        hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING) }),
        hookResult({ status: runStatus(ACTIVITY_KIND.DONE), actions: idleActions({ reviewDraftsHref: href }) }),
      ]);
      const options = requireToastOptions(expectOnlySuccessToast('Description run finished — no drafts returned.'));
      expect(options.action).toBeUndefined();
      expect(options.durationMs).toBeNull();
      expect(view.getByTestId('location')).toHaveTextContent('/people');
    });

    it.each([null, '#/workbench?hasDraft=1&run=run-1'])('DONE positive drafts keeps copy and only actionable review (%s)', (href) => {
      const view = observeSequence([
        hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING) }),
        hookResult({ status: runStatus(ACTIVITY_KIND.DONE, { draftCount: 2 }), actions: idleActions({ reviewDraftsHref: href }) }),
      ]);
      const options = requireToastOptions(expectOnlySuccessToast(GPU_STATE_VOCABULARY.doneToast(2)));
      expect(options.durationMs).toBeNull();
      if (href === null) {
        expect(options.action).toBeUndefined();
        expect(view.getByTestId('location')).toHaveTextContent('/people');
      } else {
        expect(options.action).toMatchObject({ label: GPU_STATE_VOCABULARY.reviewDrafts(2), altText: GPU_STATE_VOCABULARY.reviewDraftsAltText });
        act(() => options.action?.onClick());
        expect(view.getByTestId('location')).toHaveTextContent('/workbench?hasDraft=1&run=run-1');
      }
    });

    it('repeated DONE polls and later href alone do not emit another DONE edge', () => {
      const done = runStatus(ACTIVITY_KIND.DONE, { draftCount: 2 });
      observeSequence([
        hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING) }),
        hookResult({ status: done }),
        hookResult({ status: done }),
        hookResult({ status: done, actions: idleActions({ reviewDraftsHref: '#/workbench?hasDraft=1&run=run-1' }) }),
        hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING) }),
        hookResult({ status: done }),
      ]);
      expectOnlySuccessToast(GPU_STATE_VOCABULARY.doneToast(2));
    });

    it('review destinations and raw run tokens stay identical across locales and fallback', () => {
      const href = '#/workbench?hasDraft=1&run=run%2F1';
      for (const locale of ['en-US', 'ar-EG', 'en_US']) {
        document.documentElement.lang = locale;
        const view = observeSequence([
          hookResult({ status: runStatus(ACTIVITY_KIND.DESCRIBING, { runId: 'run/1' }) }),
          hookResult({ status: runStatus(ACTIVITY_KIND.DONE, { runId: 'run/1', draftCount: 2 }), actions: idleActions({ reviewDraftsHref: href }) }),
        ]);
        const options = requireToastOptions(expectOnlySuccessToast(GPU_STATE_VOCABULARY.doneToast(2)));
        act(() => options.action?.onClick());
        expect(view.getByTestId('location')).toHaveTextContent('/workbench?hasDraft=1&run=run%2F1');
        view.unmount();
        vi.clearAllMocks();
      }
    });
  });

});
