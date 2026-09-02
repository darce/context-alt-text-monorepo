import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import type { DescribeRunResponse } from '../../../api/describeApi';
import { BulkDescribeProgress } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%\d+\$[sd]/g, () => String(args[i++])).replace(/%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('../BulkDescribeReviewLink', () => ({
  BulkDescribeReviewLink: () => null,
}));

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: 'run-1',
  status: 'running',
  phase: 'describing',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 12,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: null,
  ...overrides,
});

const progressOf = (overrides: Partial<DescribeRunProgress> = {}): DescribeRunProgress => ({
  run: runResponse(),
  status: 'running',
  progressFraction: 0,
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

describe('BulkDescribeProgress phase copy (WBUX-6 D2)', () => {
  it('renders Queued… for the queued phase', () => {
    render(
      <BulkDescribeProgress
        progress={progressOf({
          run: runResponse({ status: 'pending', phase: 'queued' }),
          status: 'pending',
        })}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText('Queued…')).toBeInTheDocument();
  });

  it('renders warming copy and keeps Cancel live during GPU warmup', async () => {
    const onCancel = vi.fn();
    render(
      <BulkDescribeProgress
        progress={progressOf({
          run: runResponse({ phase: 'warming', completed: 0, total: 12 }),
        })}
        onRetry={vi.fn()}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByText('Warming GPU (about 2 min, first run only)…')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).toBeNull();
    const cancel = screen.getByRole('button', { name: /Cancel/ });
    expect(cancel).toBeEnabled();
    await userEvent.click(cancel);
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('renders Describing… counts and a progress bar while describing', () => {
    render(
      <BulkDescribeProgress
        progress={progressOf({
          run: runResponse({ phase: 'describing', completed: 7, total: 12 }),
          progressFraction: 7 / 12,
        })}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Describing… 7/12')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders named done-state counts, Review drafts, and Dismiss that clears the panel', async () => {
    const onReviewDrafts = vi.fn();
    const Harness = () => {
      const [visible, setVisible] = useState(true);
      if (!visible) {
        return <div>cleared</div>;
      }
      return (
        <BulkDescribeProgress
          progress={progressOf({
            run: runResponse({
              status: 'completed',
              phase: 'complete',
              completed: 12,
              failed: 2,
              total: 14,
            }),
            status: 'completed',
            isTerminal: true,
            isPolling: false,
            progressFraction: 1,
          })}
          onRetry={vi.fn()}
          onDismiss={() => setVisible(false)}
          onReviewDrafts={onReviewDrafts}
        />
      );
    };

    render(<Harness />);

    expect(screen.getByText('✔ 12 described · 2 need review')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Review drafts' }));
    expect(onReviewDrafts).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.getByText('cleared')).toBeInTheDocument();
    expect(screen.queryByText('✔ 12 described · 2 need review')).toBeNull();
  });

  it('keeps today\'s failed copy', () => {
    render(
      <BulkDescribeProgress
        progress={progressOf({
          run: runResponse({ status: 'failed', phase: 'failed', completed: 0, failed: 12, total: 12 }),
          status: 'failed',
          isTerminal: true,
          isPolling: false,
        })}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.queryByText('Warming GPU (about 2 min, first run only)…')).toBeNull();
  });

  it('keeps today\'s cancelled copy', () => {
    render(
      <BulkDescribeProgress
        progress={progressOf({
          run: runResponse({
            status: 'cancelled',
            phase: 'cancelled',
            completed: 0,
            skipped: 12,
            total: 12,
          }),
          status: 'cancelled',
          isTerminal: true,
          isPolling: false,
        })}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText('Cancelled')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull();
  });
});
