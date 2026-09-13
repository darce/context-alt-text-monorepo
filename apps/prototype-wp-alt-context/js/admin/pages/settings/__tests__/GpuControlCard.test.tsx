import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GPU_INTENT_ACTION, GPU_INTENT_STATUS, type GpuStatusResponse } from '../../../api/gpuApi';
import { GPU_STATE_VOCABULARY } from '../../workbench/gpuStatePresentation';
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

const mockControl = (data: GpuStatusResponse, overrides: Partial<ReturnType<typeof gpuControl.useGpuControl>> = {}) => {
  useGpuControlMock.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    canStart: data.gpu_state.state === 'stopped',
    startBlockedReason: null,
    canStop: data.gpu_state.state !== 'stopped' && !data.load.has_work,
    stopBlockedReason:
      data.gpu_state.state === 'stopped'
        ? 'already stopped'
        : data.load.has_work
          ? 'a describe run is in flight — stops once it finishes'
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

  it.each([
    ['Start', 'starting', 'already starting'],
    ['Stop', 'stopped', 'already stopped'],
  ] as const)(
    'keeps held %s reachable and describes its reason without opening confirmation',
    (action, state, reason) => {
      mockControl(statusResponse({ state }));
      render(<GpuControlCard />);
      const button = screen.getByRole('button', { name: action + ' GPU' });
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
    const button = screen.getByRole('button', { name: action + ' GPU' });
    expect(button).not.toHaveAttribute('aria-disabled');
    expect(button).not.toHaveAttribute('aria-describedby');
    fireEvent.click(button);
    expect(screen.getByRole('button', { name: 'Confirm ' + action.toLowerCase() })).toBeInTheDocument();
  });

  it.each(['Start', 'Stop'] as const)('holds eligible %s while an intent is pending', (action) => {
    mockControl(statusResponse({ state: action === 'Start' ? 'stopped' : 'ready' }), { isIntentPending: true });
    render(<GpuControlCard />);
    const button = screen.getByRole('button', { name: action + ' GPU' });
    expect(button).not.toHaveAttribute('disabled');
    expect(button).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(button);
    expect(screen.queryByRole('button', { name: /Confirm/ })).not.toBeInTheDocument();
  });

  it('renders the stopped automatic zero state with cost disclosure and Start enabled', () => {
    mockControl(statusResponse());
    render(<GpuControlCard />);

    expect(screen.getByRole('heading', { name: 'Settings › Burst GPU' })).toBeInTheDocument();
    expect(screen.getByText(`${GPU_STATE_VOCABULARY.tierPrefix} ${GPU_STATE_VOCABULARY.stopped}`)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start GPU' })).toBeEnabled();
    expect(screen.getByRole('button', { name: /Stop GPU/ })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText(/\$2\.00 \/ GPU-hour/)).toBeInTheDocument();
    expect(screen.getByTestId('z-gpu-state-chip')).toHaveAttribute('role', 'status');
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('shows the inline start preview before committing', () => {
    const requestIntent = vi.fn();
    mockControl(statusResponse(), { requestIntent });
    render(<GpuControlCard />);
    fireEvent.click(screen.getByRole('button', { name: 'Start GPU' }));

    expect(screen.getByText('Confirm start')).toBeInTheDocument();
    expect(screen.getByText(/Returns to automatic after 30 min/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm start' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm start' }));
    expect(requestIntent).toHaveBeenCalledWith(GPU_INTENT_ACTION.START);
  });

  it('renders warm-up ETA and the faster polling note', () => {
    mockControl(
      statusResponse({
        state: 'warming',
        intent: GPU_INTENT_ACTION.START,
        instance_running_since: '2026-09-07T11:59:00Z',
      }),
    );
    render(<GpuControlCard />);

    expect(screen.getByText(`${GPU_STATE_VOCABULARY.tierPrefix} ${GPU_STATE_VOCABULARY.warming}`)).toBeInTheDocument();
    expect(screen.getByText(/Warming… about/)).toBeInTheDocument();
    expect(screen.getByText(/polling every 5 s/)).toBeInTheDocument();
  });

  it('disables Stop with the work-in-flight reason', () => {
    mockControl(statusResponse({ state: 'ready' }), {
      canStop: false,
      stopBlockedReason: 'a describe run is in flight — stops once it finishes',
    });
    render(<GpuControlCard />);

    expect(screen.getByRole('button', { name: /Stop GPU/ })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText(/a describe run is in flight/)).toBeInTheDocument();
  });

  it('renders a pending stop notice for blocked work', () => {
    mockControl(
      statusResponse({
        state: 'degraded',
        intent: GPU_INTENT_ACTION.STOP,
        intent_status: GPU_INTENT_STATUS.BLOCKED_WORK_IN_FLIGHT,
      }),
    );
    render(<GpuControlCard />);

    expect(screen.getByText(/Stop pending/)).toBeInTheDocument();
    expect(screen.getByText(/stops when it ends/)).toBeInTheDocument();
  });

  it('renders stale telemetry as not reported and disables Start with its age', () => {
    mockControl(
      { ...statusResponse({ state: 'ready' }), snapshot_age_seconds: 240, snapshot_fresh: false },
      {
        canStart: false,
        startBlockedReason: 'Lifecycle telemetry is stale — refresh before starting the GPU.',
      },
    );
    render(<GpuControlCard />);

    expect(
      screen.getByText(`${GPU_STATE_VOCABULARY.tierPrefix} ${GPU_STATE_VOCABULARY.notReported}`),
    ).toBeInTheDocument();
    expect(screen.getByText(/last snapshot 4 min ago \(stale\)/)).toBeInTheDocument();
    expect(screen.getByText(/Lifecycle telemetry is stale/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start GPU' })).toHaveAttribute('aria-disabled', 'true');
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
