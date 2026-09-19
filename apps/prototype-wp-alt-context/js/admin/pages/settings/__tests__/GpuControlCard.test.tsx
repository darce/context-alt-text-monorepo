import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GPU_INTENT_ACTION, GPU_INTENT_STATUS, GPU_STATE, type GpuStatusResponse } from '../../../api/gpuApi';
import { HTTPError } from '../../../utils/http';
import { GPU_STATE_VOCABULARY } from '../../workbench/gpuStatePresentation';
import { GpuControlCard } from '../GpuControlCard';
import * as gpuControl from '../useGpuControl';
import serviceStates from './fixtures/gpuflow-service-states.json';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

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
    isFetching: false,
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
    intentError: null,
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
    mockControl(
      statusResponse({
        state: action === 'Start' ? 'stopped' : 'ready',
        instance_running_since: '2026-09-07T11:59:00Z',
        lease_expires_at: '2026-09-07T12:59:00Z',
      }),
    );
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

  it.each(['starting', 'warming'] as const)('shows warming copy without an invented countdown while %s', (state) => {
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
  });

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
    expect(screen.getByText('Stop after the current run finishes?')).toBeInTheDocument();
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
    expect(screen.getByText('Stopping after the current work finishes until idle')).toBeInTheDocument();
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

    expect(screen.getByText('Stopping after the current work finishes until idle')).toBeInTheDocument();
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
    expect(screen.getByRole('button', { name: 'Return to automatic' })).toBeInTheDocument();
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
    expect(screen.getByRole('button', { name: 'Return to automatic' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });

  it('omits Return to automatic on unknown when intent is already automatic', () => {
    mockControl(statusResponse({ state: 'unknown' }), {
      canStart: false,
      canStop: false,
      canReturnToAuto: false,
    });
    render(<GpuControlCard />);

    expect(screen.queryByRole('button', { name: 'Start service' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Stop service/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Return to automatic' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });

  it('clears an open stop confirmation when the snapshot becomes stale', () => {
    const requestIntent = vi.fn();
    mockControl(statusResponse({ state: 'ready' }), { requestIntent });
    const { rerender } = render(<GpuControlCard />);
    fireEvent.click(screen.getByRole('button', { name: /Stop service/ }));
    expect(screen.getByRole('button', { name: 'Confirm stop' })).toBeInTheDocument();

    mockControl(
      {
        ...statusResponse({ state: 'ready' }),
        snapshot_age_seconds: 240,
        snapshot_fresh: false,
      },
      { requestIntent, canStart: false, canStop: false },
    );
    rerender(<GpuControlCard />);

    expect(screen.queryByTestId('z-stop-preview')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm stop' })).not.toBeInTheDocument();
    expect(requestIntent).not.toHaveBeenCalled();
  });

  it('clears an open start confirmation when the snapshot becomes stale', () => {
    const requestIntent = vi.fn();
    mockControl(statusResponse(), { requestIntent });
    const { rerender } = render(<GpuControlCard />);
    fireEvent.click(screen.getByRole('button', { name: 'Start service' }));
    expect(screen.getByRole('button', { name: 'Confirm start' })).toBeInTheDocument();

    mockControl(
      {
        ...statusResponse(),
        snapshot_age_seconds: 240,
        snapshot_fresh: false,
      },
      { requestIntent, canStart: false, canStop: false },
    );
    rerender(<GpuControlCard />);

    expect(screen.queryByTestId('z-start-preview')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm start' })).not.toBeInTheDocument();
    expect(requestIntent).not.toHaveBeenCalled();
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

  it('renders an initial fetch error with Refresh and announces it', () => {
    const refetch = vi.fn();
    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      error: new Error('502 Bad Gateway'),
      refetch,
    });
    render(<GpuControlCard />);

    const chip = screen.getByTestId('z-gpu-state-chip');
    expect(chip).toHaveAttribute('aria-live', 'polite');
    expect(chip).toHaveTextContent(/Could not reach the description service \(502\)/);
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    const refresh = screen.getByRole('button', { name: 'Refresh' });
    expect(refresh).toBeEnabled();
    fireEvent.click(refresh);
    expect(refetch).toHaveBeenCalledOnce();
  });

  it('disables Refresh while refetching after an initial fetch error', () => {
    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      isFetching: true,
      error: new Error('502 Bad Gateway'),
      refetch: vi.fn(),
    });
    render(<GpuControlCard />);

    expect(screen.getByRole('button', { name: 'Refresh' })).toBeDisabled();
  });

  it('clears a start confirmation when start becomes disallowed even if stop remains allowed', () => {
    const requestIntent = vi.fn();
    mockControl(statusResponse(), { requestIntent, canStart: true, canStop: false });
    const { rerender } = render(<GpuControlCard />);
    fireEvent.click(screen.getByRole('button', { name: 'Start service' }));
    expect(screen.getByRole('button', { name: 'Confirm start' })).toBeInTheDocument();

    mockControl(
      {
        ...statusResponse({ state: 'ready', instance_running_since: '2026-09-07T11:00:00Z' }),
        load: { has_work: true, written_at: 1_700_000_004, fresh: true },
      },
      {
        requestIntent,
        canStart: false,
        canStop: true,
        startBlockedReason: 'already running',
      },
    );
    rerender(<GpuControlCard />);

    expect(screen.queryByTestId('z-start-preview')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm start' })).not.toBeInTheDocument();
    expect(screen.getByTestId('gpu-confirmation-cleared-reason')).toHaveTextContent('already running');
    expect(screen.getByTestId('z-gpu-state-chip')).toHaveTextContent('already running');
    expect(requestIntent).not.toHaveBeenCalled();
  });

  it('only shows Return to automatic when intent is not automatic', () => {
    mockControl(statusResponse({ intent: GPU_INTENT_ACTION.START }));
    render(<GpuControlCard />);
    expect(screen.getByRole('button', { name: 'Return to automatic' })).toBeEnabled();
  });

  const unavailableError = (
    checkedAt: string,
    overrides: {
      reason?: string;
      service?: string;
      http_status?: number | null;
      retry_after_seconds?: number | null;
    } = {},
  ) =>
    Object.assign(new Error('502 Bad Gateway'), {
      unavailable: {
        reason: 'circuit_open',
        service: 'scene',
        http_status: 502,
        retry_after_seconds: 30,
        checked_at: checkedAt,
        ...overrides,
      },
    });

  it('names the service, reason, fix, last checked, and retry countdown from unavailable', () => {
    const refetch = vi.fn();
    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      error: unavailableError('2026-09-18T14:03:22Z'),
      refetch,
    });
    render(<GpuControlCard />);

    expect(screen.queryByText(/Could not reach the description service/)).not.toBeInTheDocument();
    expect(
      screen.getByText('Description service is unavailable because the circuit breaker is open.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Wait for the cooldown, then Retry.')).toBeInTheDocument();
    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
    expect(screen.getByText('Retry in 30 s')).toBeInTheDocument();
    expect(screen.getByTestId('gpu-unavailable-icon')).toBeInTheDocument();
    expect(screen.getByTestId('gpu-unavailable-status')).toHaveAttribute('data-tone', 'warning');
    expect(screen.getByTestId('gpu-unavailable-status')).toHaveClass('acx-sync-status--warning');
    expect(screen.queryByRole('button', { name: 'Refresh' })).not.toBeInTheDocument();
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect(retry).toBeEnabled();
    fireEvent.click(retry);
    expect(refetch).toHaveBeenCalledOnce();
  });

  it('updates last checked after Retry and keeps Retry pending while fetching', () => {
    const refetch = vi.fn();
    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      error: unavailableError('2026-09-18T14:03:22Z'),
      refetch,
    });
    const { rerender } = render(<GpuControlCard />);

    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledOnce();

    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      error: unavailableError('2026-09-18T14:03:22Z'),
      isFetching: true,
      refetch,
    });
    rerender(<GpuControlCard />);
    expect(screen.getByRole('button', { name: 'Fetching…' })).toBeDisabled();
    expect(screen.getByTestId('gpu-unavailable-status')).toHaveTextContent('Checking service status…');
    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();

    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      error: unavailableError('2026-09-18T14:04:05Z'),
      refetch,
    });
    rerender(<GpuControlCard />);
    expect(screen.getByText('Last checked 14:04:05')).toBeInTheDocument();
    expect(screen.queryByText('Last checked 14:03:22')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  });

  it('omits a retry countdown when unavailable retry_after_seconds is absent', () => {
    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      error: unavailableError('2026-09-18T14:03:22Z', { retry_after_seconds: null }),
      refetch: vi.fn(),
    });
    render(<GpuControlCard />);

    expect(screen.getByText('Last checked 14:03:22')).toBeInTheDocument();
    expect(screen.queryByText(/Retry in /)).not.toBeInTheDocument();
    expect(screen.queryByText(/Retrying in 15 s/)).not.toBeInTheDocument();
  });

  it('uses generic copy plus the reason code for an unknown unavailable reason', () => {
    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      error: unavailableError('2026-09-18T14:03:22Z', { reason: 'mystery_code', retry_after_seconds: null }),
      refetch: vi.fn(),
    });
    render(<GpuControlCard />);

    expect(
      screen.getByText('Description service is unavailable because an unexpected error occurred (mystery_code).'),
    ).toBeInTheDocument();
    expect(screen.getByText('Retry. If it continues, check Settings and the service logs.')).toBeInTheDocument();
  });

  it('renders specific unavailable copy from a typed envelope when bodyPreview is truncated', () => {
    const payload = {
      code: 'acx_service_unavailable',
      message: `The description service is unavailable. ${'x'.repeat(500)}`,
      data: {
        status: 503,
        unavailable: {
          reason: 'timeout',
          service: 'scene',
          http_status: 503,
          retry_after_seconds: 15,
          checked_at: '2026-09-18T14:03:22Z',
        },
      },
    };
    const raw = JSON.stringify(payload);
    expect(raw.length).toBeGreaterThan(600);
    const truncated = `${raw.replace(/\s+/g, ' ').trim().slice(0, 240)}...`;
    expect(() => JSON.parse(truncated)).toThrow();

    mockControl(statusResponse(), {
      data: undefined,
      isError: true,
      error: new HTTPError({
        status: 503,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/gpu/status',
        bodyPreview: truncated,
        unavailable: {
          reason: 'timeout',
          service: 'scene',
          http_status: 503,
          retry_after_seconds: 15,
          checked_at: '2026-09-18T14:03:22Z',
        },
        message: `Request to /acx/v1/gpu/status failed (503): ${raw}`,
      }),
      refetch: vi.fn(),
    });
    render(<GpuControlCard />);

    expect(
      screen.getByText('Description service is unavailable because it did not respond in time.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Retry. If it continues, check that the host is reachable.')).toBeInTheDocument();
  });

  it('shows the unavailable reason when a start intent is rejected with an envelope', () => {
    mockControl(statusResponse(), {
      intentError: unavailableError('2026-09-18T14:03:22Z'),
    });
    render(<GpuControlCard />);

    expect(
      screen.getByText('Description service is unavailable because the circuit breaker is open.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Wait for the cooldown, then Retry.')).toBeInTheDocument();
    expect(screen.queryByTestId('gpu-intent-failure')).not.toBeInTheDocument();
  });

  it('shows a generic alert when a stop intent is rejected without an envelope', () => {
    const requestIntent = vi.fn();
    mockControl(statusResponse({ state: 'ready' }), { requestIntent });
    const { rerender } = render(<GpuControlCard />);
    fireEvent.click(screen.getByRole('button', { name: 'Stop service' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm stop' }));
    expect(requestIntent).toHaveBeenCalledWith(GPU_INTENT_ACTION.STOP);

    mockControl(statusResponse({ state: 'ready' }), {
      requestIntent,
      intentError: new Error('500 Internal Server Error'),
    });
    rerender(<GpuControlCard />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Stop request failed');
    expect(alert).toHaveClass('notice-error');
    expect(screen.getByTestId('gpu-intent-failure-icon')).toBeInTheDocument();
    expect(screen.queryByText(/the circuit breaker is open/)).not.toBeInTheDocument();
  });
});
