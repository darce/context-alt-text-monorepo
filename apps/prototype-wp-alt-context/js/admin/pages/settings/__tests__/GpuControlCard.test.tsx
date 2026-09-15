import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GPU_INTENT_ACTION, GPU_INTENT_STATUS, GPU_STATE, type GpuStatusResponse } from '../../../api/gpuApi';
import { GPU_STATE_VOCABULARY } from '../../workbench/gpuStatePresentation';
import serviceStates from './fixtures/gpuflow-service-states.json';
import { GpuControlCard } from '../GpuControlCard';
import * as gpuControl from '../useGpuControl';

vi.mock('../useGpuControl', async (importOriginal) => {
  const actual = await importOriginal<typeof gpuControl>();
  return { ...actual, useGpuControl: vi.fn() };
});

const useGpuControlMock = vi.mocked(gpuControl.useGpuControl);

const statusResponse = (overrides: Partial<GpuStatusResponse['gpu_state']> = {}): GpuStatusResponse => ({
  gpu_state: {
    state: 'stopped',
    instance_id: null,
    written_at: 1_700_000_000,
    reason: null,
    since: null,
    intent: GPU_INTENT_ACTION.AUTO,
    intent_expires_at: null,
    intent_status: GPU_INTENT_STATUS.NONE,
    honoured_nonce: null,
    lease_expires_at: null,
    instance_running_since: null,
    last_transition_reason: 'unknown',
    ...overrides,
  },
  snapshot_age_seconds: 12,
  snapshot_fresh: true,
  intent: null,
  load: { has_work: false, written_at: 1_700_000_004, fresh: true },
  server_time: '2026-09-07T12:00:00Z',
});

const STOPPABLE_STATES = new Set(['starting', 'warming', 'ready', 'degraded']);

const mockControl = (data: GpuStatusResponse, overrides: Partial<ReturnType<typeof gpuControl.useGpuControl>> = {}) => {
  const effectiveState = data.snapshot_fresh ? data.gpu_state.state : undefined;
  useGpuControlMock.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    canStart:
      effectiveState !== undefined &&
      (effectiveState === 'stopped' || effectiveState === 'degraded') &&
      data.gpu_state.intent !== GPU_INTENT_ACTION.START,
    startBlockedReason: null,
    canStop:
      effectiveState !== undefined &&
      STOPPABLE_STATES.has(effectiveState) &&
      data.gpu_state.intent !== GPU_INTENT_ACTION.STOP,
    stopBlockedReason:
      data.gpu_state.state === 'stopped'
        ? 'already stopped'
        : data.gpu_state.intent === GPU_INTENT_ACTION.STOP
          ? 'stop already requested'
          : null,
    canReturnToAuto: data.gpu_state.intent !== GPU_INTENT_ACTION.AUTO,
    requestIntent: vi.fn(),
    isIntentPending: false,
    ...overrides,
  } as ReturnType<typeof gpuControl.useGpuControl>);
};

describe('GpuControlCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each(serviceStates.states)('renders service state $state', ({ state, label, tone }) => {
    mockControl(statusResponse({ state: state as GpuStatusResponse['gpu_state']['state'] }));
    render(<GpuControlCard />);
    expect(screen.getByText(label).closest('[data-tone]')).toHaveAttribute('data-tone', tone);
  });

  it.each([
    ['Start', 'starting', 'already starting'],
    ['Stop', 'stopped', 'already stopped'],
  ] as const)(
    'keeps held %s reachable and describes its reason without opening confirmation',
    (action, state, reason) => {
      mockControl(statusResponse({ state }));
      render(<GpuControlCard />);
      const button = screen.getByRole('button', { name: action + ' service' });
      expect(button).not.toHaveAttribute('disabled');
      expect(button).toHaveAttribute('aria-disabled', 'true');
      expect(button.tabIndex).toBe(0);
      button.focus();
      expect(button).toHaveFocus();
      const description = document.getElementById(button.getAttribute('aria-describedby') ?? '');
      expect(description).toBeVisible();
      expect(description).toHaveTextContent('disabled: ' + reason);
      fireEvent.click(button);
      expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument();
    },
  );

  it.each(['Start', 'Stop'] as const)('opens confirmation for eligible %s', (action) => {
    mockControl(statusResponse({ state: action === 'Start' ? 'stopped' : 'ready' }));
    render(<GpuControlCard />);
    const button = screen.getByRole('button', { name: action + ' service' });
    expect(button).not.toHaveAttribute('aria-disabled');
    expect(button).not.toHaveAttribute('aria-describedby');
    fireEvent.click(button);
    expect(screen.getByRole('button', { name: 'Confirm ' + action.toLowerCase() })).toBeInTheDocument();
  });

  it.each(['Start', 'Stop'] as const)('holds eligible %s while an intent is pending', (action) => {
    mockControl(statusResponse({ state: action === 'Start' ? 'stopped' : 'ready' }), { isIntentPending: true });
    render(<GpuControlCard />);
    const button = screen.getByRole('button', { name: action + ' service' });
    expect(button).not.toHaveAttribute('disabled');
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button.tabIndex).toBe(0);
    button.focus();
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute('aria-describedby', `z-gpu-${action.toLowerCase()}-reason`);
    const description = document.getElementById(button.getAttribute('aria-describedby') ?? '');
    expect(description).toBeVisible();
    expect(description).toHaveTextContent('disabled: a service request is already in flight');
    fireEvent.click(button);
    expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument();
  });

  it('renders the stopped automatic zero state with cost disclosure and Start enabled', () => {
    mockControl(statusResponse());
    render(<GpuControlCard />);

    expect(screen.getByRole('heading', { name: 'Settings › Description Service' })).toBeInTheDocument();
    expect(screen.getByText(`Service: ${GPU_STATE_VOCABULARY.stopped}`)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start service' })).toBeEnabled();
    expect(screen.getByRole('button', { name: /Stop service/ })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText(/\$2\.00 \/ service-hour/)).toBeInTheDocument();
    expect(screen.getByTestId('z-gpu-state-chip')).toHaveAttribute('role', 'status');
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it.each(['Start', 'Stop'] as const)('uses plain operator copy in the %s confirmation', (action) => {
    mockControl(statusResponse({
      state: action === 'Start' ? 'stopped' : 'ready',
      instance_running_since: '2026-09-07T11:59:00Z',
      lease_expires_at: '2026-09-07T12:59:00Z',
    }));
    const { container } = render(<GpuControlCard />);
    fireEvent.click(screen.getByRole('button', { name: action + ' service' }));
    expect(screen.getByTestId('z-gpu-lease')).toHaveTextContent('Run limit:');
    expect(container).not.toHaveTextContent(/Burst GPU|A10|lease/i);
  });

  it('shows the inline start preview before committing', () => {
    const requestIntent = vi.fn();
    mockControl(statusResponse(), { requestIntent });
    render(<GpuControlCard />);
    fireEvent.click(screen.getByRole('button', { name: 'Start service' }));

    expect(screen.getByText('Confirm start')).toBeInTheDocument();
    expect(screen.getByText(/Returns to automatic after 30 min/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm start' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm start' }));
    expect(requestIntent).toHaveBeenCalledWith(GPU_INTENT_ACTION.START);
  });

  it.each(['starting', 'warming'] as const)(
    'shows warming copy without an invented countdown while %s',
    (state) => {
      mockControl(
        statusResponse({
          state,
          intent: GPU_INTENT_ACTION.START,
          instance_running_since: '2026-09-07T11:59:00Z',
        }),
      );
      render(<GpuControlCard />);

      expect(screen.getByText(`Service: ${GPU_STATE_VOCABULARY[state]}`)).toBeInTheDocument();
      const warmup = screen.getByTestId('gpu-warmup-eta');
      expect(warmup).toHaveTextContent('Warming up, this can take a few minutes');
      expect(warmup).not.toHaveTextContent(/\d/);
    },
  );

  it('keeps Stop enabled during work in flight and shows deferred-stop copy', () => {
    const requestIntent = vi.fn();
    const busy = {
      ...statusResponse({
        state: 'ready',
        instance_running_since: '2026-09-07T11:59:00Z',
      }),
      load: { has_work: true, written_at: 1_700_000_004, fresh: true },
    };
    mockControl(busy, { requestIntent });
    const { rerender } = render(<GpuControlCard />);

    const stop = screen.getByRole('button', { name: /Stop service/ });
    expect(stop).not.toHaveAttribute('disabled');
    expect(stop).not.toHaveAttribute('aria-disabled');
    fireEvent.click(stop);
    expect(screen.getByText(/Stopping after the current work finishes/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm stop' }));
    expect(requestIntent).toHaveBeenCalledWith(GPU_INTENT_ACTION.STOP);

    mockControl(
      {
        ...busy,
        gpu_state: {
          ...busy.gpu_state,
          intent: GPU_INTENT_ACTION.STOP,
          intent_status: GPU_INTENT_STATUS.BLOCKED_WORK_IN_FLIGHT,
        },
      },
      { requestIntent },
    );
    rerender(<GpuControlCard />);
    expect(screen.getByText(`Service: ${GPU_STATE_VOCABULARY.ready}`)).toBeInTheDocument();
    expect(screen.getByText(/Stopping after the current work finishes/)).toBeInTheDocument();
  });

  it('renders a pending stop notice for blocked work', () => {
    mockControl({
      ...statusResponse({
        state: 'degraded',
        intent: GPU_INTENT_ACTION.STOP,
        intent_status: GPU_INTENT_STATUS.BLOCKED_WORK_IN_FLIGHT,
      }),
      load: { has_work: true, written_at: 1_700_000_004, fresh: true },
    });
    render(<GpuControlCard />);

    expect(screen.getByText(/Stopping after the current work finishes/)).toBeInTheDocument();
    expect(screen.getByText(`Service: ${GPU_STATE_VOCABULARY.degraded}`)).toBeInTheDocument();
  });

  it('disables Stop when the service is already stopped', () => {
    mockControl(statusResponse({ state: 'stopped' }));
    render(<GpuControlCard />);
    expect(screen.getByRole('button', { name: /Stop service/ })).toHaveAttribute('aria-disabled', 'true');
  });

  it('hides Start and Stop when the snapshot is stale and keeps Refresh', () => {
    mockControl(
      {
        ...statusResponse({ state: 'ready', intent: GPU_INTENT_ACTION.START }),
        snapshot_age_seconds: 240,
        snapshot_fresh: false,
      },
      {
        canStart: false,
        canStop: false,
        canReturnToAuto: true,
        startBlockedReason: 'Lifecycle telemetry is stale — refresh before starting the GPU.',
      },
    );
    render(<GpuControlCard />);

    expect(screen.getByText(`Service: ${GPU_STATE_VOCABULARY.notReported}`)).toBeInTheDocument();
    expect(screen.getByText(/last snapshot 4 min ago \(stale\)/)).toBeInTheDocument();
    expect(screen.getByTestId('gpu-stale-notice')).toHaveTextContent('Service status is out of date');
    expect(screen.queryByRole('button', { name: 'Start service' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Stop service/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Return to automatic' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });

  it('hides Start and Stop when the service state is unknown and keeps Refresh', () => {
    mockControl(statusResponse({ state: 'unknown', intent: GPU_INTENT_ACTION.START }), {
      canStart: false,
      canStop: false,
      canReturnToAuto: true,
    });
    render(<GpuControlCard />);

    expect(screen.getByText(`Service: ${GPU_STATE_VOCABULARY.notReported}`)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start service' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Stop service/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Return to automatic' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });

  it.each([
    [GPU_STATE.STOPPED, true, 'a service request is already in flight'],
    [GPU_STATE.STARTING, true, 'a service request is already in flight'],
  ] as const)('explains held Start for %s while pending', (state, pending, expected) => {
    mockControl(
      { ...statusResponse({ state }), snapshot_fresh: true },
      {
        canStart: false,
        startBlockedReason: null,
        isIntentPending: pending,
      },
    );
    render(<GpuControlCard />);

    const button = screen.getByRole('button', { name: 'Start service' });
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).toHaveAttribute('aria-describedby', 'z-gpu-start-reason');
    const description = document.getElementById('z-gpu-start-reason');
    expect(description).toBeVisible();
    expect(description).toHaveTextContent(`disabled: ${expected}`);
    expect(description).not.toHaveTextContent('already stopped');
    fireEvent.click(button);
    expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument();
  });

  it('renders a 502 error with a retry control', () => {
    const refetch = vi.fn();
    mockControl(statusResponse(), { data: undefined, isError: true, error: new Error('502 Bad Gateway'), refetch });
    render(<GpuControlCard />);

    expect(screen.getByText(/Could not reach the description service \(502\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it('only shows Return to automatic when intent is not automatic', () => {
    mockControl(statusResponse({ intent: GPU_INTENT_ACTION.START }));
    render(<GpuControlCard />);
    expect(screen.getByRole('button', { name: 'Return to automatic' })).toBeEnabled();
  });
});
