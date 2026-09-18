import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { GPU_STATE } from '../../../api/describeApi';
import {
  ACTIVITY_KIND,
  ACTIVITY_REASON,
  type ActivityStatus,
  type UseActivityStatusResult,
} from '../../../hooks/useActivityStatus';
import { ActivityStatusStrip } from '../ActivityStatusStrip';

const useActivityStatusMock = vi.hoisted(() => vi.fn());
const setAdvancedOpenMock = vi.hoisted(() => vi.fn());
const setDescribeProgressMountedMock = vi.hoisted(() => vi.fn());

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return fmt.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

vi.mock('../../../hooks/useActivityStatus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../hooks/useActivityStatus')>();
  return {
    ...actual,
    useActivityStatus: (params: unknown) => useActivityStatusMock(params),
  };
});

vi.mock('../WorkbenchNavContext', () => ({
  useWorkbenchNav: () => ({
    isAdvancedOpen: false,
    setAdvancedOpen: setAdvancedOpenMock,
  }),
}));

vi.mock('../../../hooks/activeDescribeRun', () => ({
  setDescribeProgressMounted: setDescribeProgressMountedMock,
}));

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

const hookResult = (overrides: Partial<UseActivityStatusResult> = {}): UseActivityStatusResult => ({
  status: idleStatus(),
  actions: {
    onCancel: null,
    onRetry: null,
    reviewDraftsHref: null,
    backToRunHref: null,
  },
  isCancelling: false,
  ...overrides,
});

describe('ActivityStatusStrip', () => {
  it('announces in a polite status region and marks the strip as mounted', () => {
    useActivityStatusMock.mockReturnValue(
      hookResult({
        status: idleStatus({ kind: ACTIVITY_KIND.WARMING, etaSeconds: 180, canCancel: true, runId: 'run-1' }),
        actions: {
          onCancel: vi.fn(),
          onRetry: null,
          reviewDraftsHref: null,
          backToRunHref: '#/workbench',
        },
      }),
    );

    const { unmount } = render(<ActivityStatusStrip />);

    const region = screen.getByRole('status');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByText('Warming GPU (first run only)…')).toBeTruthy();
    expect(screen.getByText('~3m 0s remaining')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel run' })).toBeEnabled();
    expect(screen.getByRole('link', { name: 'Back to run' })).toHaveAttribute('href', '#/workbench');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(setDescribeProgressMountedMock).toHaveBeenCalledWith(true);

    unmount();
    expect(setDescribeProgressMountedMock).toHaveBeenCalledWith(false);
  });

  it('opens the non-modal AdvancedDrawer from Details, not a blocking dialog', async () => {
    useActivityStatusMock.mockReturnValue(
      hookResult({
        status: idleStatus({ kind: ACTIVITY_KIND.DESCRIBING, progress: 0.5, etaSeconds: 40, canCancel: true }),
        actions: {
          onCancel: vi.fn(),
          onRetry: null,
          reviewDraftsHref: null,
          backToRunHref: '#/workbench',
        },
      }),
    );

    render(<ActivityStatusStrip />);

    await userEvent.click(screen.getByRole('button', { name: 'Details' }));
    expect(setAdvancedOpenMock).toHaveBeenCalledWith(true);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('confirms Cancel run in a dialog and does not cancel on dismiss', async () => {
    const onCancel = vi.fn();
    useActivityStatusMock.mockReturnValue(
      hookResult({
        status: idleStatus({
          kind: ACTIVITY_KIND.DESCRIBING,
          progress: 0.25,
          etaSeconds: 20,
          canCancel: true,
          runId: 'run-1',
        }),
        actions: {
          onCancel,
          onRetry: null,
          reviewDraftsHref: null,
          backToRunHref: '#/workbench',
        },
      }),
    );

    render(<ActivityStatusStrip />);

    await userEvent.click(screen.getByRole('button', { name: 'Cancel run' }));
    expect(screen.getByRole('heading', { name: 'Cancel this run?' })).toBeTruthy();
    expect(onCancel).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('keeps Review drafts, Retry, and Back to run available from the strip', () => {
    useActivityStatusMock.mockReturnValue(
      hookResult({
        status: idleStatus({
          kind: ACTIVITY_KIND.DONE,
          runId: 'run-9',
          draftCount: 4,
          gpuState: GPU_STATE.READY,
        }),
        actions: {
          onCancel: null,
          onRetry: null,
          reviewDraftsHref: '#/description-history?run=run-9',
          backToRunHref: null,
        },
      }),
    );

    const { rerender } = render(<ActivityStatusStrip />);
    expect(screen.getByRole('link', { name: 'Review 4 drafts' })).toHaveAttribute(
      'href',
      '#/description-history?run=run-9',
    );

    const onRetry = vi.fn();
    useActivityStatusMock.mockReturnValue(
      hookResult({
        status: idleStatus({
          kind: ACTIVITY_KIND.FAILED,
          reason: ACTIVITY_REASON.GPU_WARMUP_TIMEOUT,
          retryable: true,
          runId: 'run-9',
        }),
        actions: {
          onCancel: null,
          onRetry,
          reviewDraftsHref: null,
          backToRunHref: null,
        },
      }),
    );
    rerender(<ActivityStatusStrip />);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByText('GPU warm-up timed out. Retry to continue.')).toBeTruthy();
  });
});

describe('ActivityStatusStrip cancel confirm (dialog only for cancel)', () => {
  it('calls onCancel only after confirm', async () => {
    const onCancel = vi.fn();
    useActivityStatusMock.mockReturnValue(
      hookResult({
        status: idleStatus({
          kind: ACTIVITY_KIND.WARMING,
          etaSeconds: 120,
          canCancel: true,
          runId: 'run-1',
        }),
        actions: {
          onCancel,
          onRetry: null,
          reviewDraftsHref: null,
          backToRunHref: '#/workbench',
        },
      }),
    );

    render(<ActivityStatusStrip />);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel run' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('heading', { name: 'Cancel this run?' })).toBeTruthy();
    expect(onCancel).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel run' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
