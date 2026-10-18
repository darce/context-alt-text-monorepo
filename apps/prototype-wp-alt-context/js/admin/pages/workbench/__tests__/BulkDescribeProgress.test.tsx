import { render, screen } from '@testing-library/react';
import { act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import type { DescribeRunResponse } from '../../../api/describeApi';
import { HTTPError } from '../../../utils/http';
import { _resetCooldownForTests, openCooldown } from '../../../utils/recognitionCooldown';
import { BulkDescribeProgress } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('../BulkDescribeReviewLink', () => ({
  BulkDescribeReviewLink: () => null,
}));

const PAUSED_LABEL = 'Waiting for the service — progress updates paused.';
const COUNTDOWN_SELECTOR = '.acx-media-selection__bulk-describe-countdown';

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: 'run-1',
  status: 'running',
  phase: 'describing',
  completed: 1,
  failed: 0,
  skipped: 0,
  total: 4,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: null,
  // Snapshot of the site's recognition setting at submit (schema default true); this test's world is recognition-on.
  recognition_enabled: true,
  ...overrides,
});

const progressOf = (overrides: Partial<DescribeRunProgress> = {}): DescribeRunProgress => ({
  run: runResponse(),
  status: 'running',
  progressFraction: 0.25,
  etaSeconds: null,
  isTerminal: false,
  stalledForSeconds: null,
  isPolling: true,
  isFrozen: false,
  isError: false,
  error: null,
  retry: vi.fn(),
  ...overrides,
});

describe('BulkDescribeProgress a11y countdown (polite region does not re-announce every second)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T12:00:00.000Z'));
    _resetCooldownForTests();
  });

  afterEach(() => {
    _resetCooldownForTests();
    vi.useRealTimers();
  });

  it('keeps the announced sentence static while only the aria-hidden countdown ticks', () => {
    act(() => {
      openCooldown(5);
    });

    const { container } = render(<BulkDescribeProgress progress={progressOf()} onRetry={vi.fn()} />);

    // Announced sentence is its own (non-aria-hidden) node and is stable.
    const label = screen.getByText(PAUSED_LABEL);
    expect(label).not.toHaveAttribute('aria-hidden');

    const countdown = container.querySelector(COUNTDOWN_SELECTOR);
    expect(countdown).not.toBeNull();
    expect(countdown).toHaveAttribute('aria-hidden', 'true');
    expect(countdown).toHaveTextContent('Retrying in 5s.');

    // One second passes: the visible countdown ticks, the announced sentence does not.
    act(() => {
      vi.advanceTimersByTime(1_000);
    });

    expect(screen.getByText(PAUSED_LABEL)).toBeInTheDocument();
    expect(container.querySelector(COUNTDOWN_SELECTOR)).toHaveTextContent('Retrying in 4s.');
    // The announced sentence never carries the ticking count.
    expect(screen.getByText(PAUSED_LABEL).textContent).toBe(PAUSED_LABEL);
  });
});

describe('BulkDescribeProgress cooldown-vs-error precedence', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T12:00:00.000Z'));
    _resetCooldownForTests();
  });

  afterEach(() => {
    _resetCooldownForTests();
    vi.useRealTimers();
  });

  it('prefers the paused notice over the assertive retry alert when a 429 hard error meets an armed cooldown', () => {
    act(() => {
      openCooldown(30);
    });

    const error = new HTTPError({
      status: 429,
      retryAfterSeconds: 30,
      endpoint: '/acx/v1/recognition/describe/runs/run-1',
      bodyPreview: '',
      message: 'failed (429)',
    });

    render(<BulkDescribeProgress progress={progressOf({ isError: true, error })} onRetry={vi.fn()} />);

    // Waiting notice wins; the assertive Retry alert is suppressed.
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText(PAUSED_LABEL)).toBeInTheDocument();
    expect(screen.queryByText('Progress updates paused. Retry to resume.')).toBeNull();
  });

  it('still shows the assertive retry alert for a non-cooldown hard error', () => {
    render(
      <BulkDescribeProgress
        progress={progressOf({ isError: true, error: new Error('describe run lost') })}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Progress updates paused. Retry to resume.')).toBeInTheDocument();
    expect(screen.queryByText(PAUSED_LABEL)).toBeNull();
  });
});
