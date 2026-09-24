import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
  beforeEach(() => {
    vi.clearAllMocks();
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
              canCancel: true,
            }),
          }),
        ],
        { mounted: true },
      );
      const options = expectOnlyErrorToast(GPU_STATE_VOCABULARY.degradedToast);
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
});
