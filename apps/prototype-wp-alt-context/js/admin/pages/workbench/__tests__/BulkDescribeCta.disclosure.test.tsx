import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import { BulkDescribeCta } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('../BulkDescribeReviewLink', () => ({
  BulkDescribeReviewLink: () => null,
}));

const idleProgress = {
  status: null,
  run: null,
  isTerminal: false,
  isError: false,
  isPolling: false,
  etaSeconds: null,
  progressFraction: 0,
  retry: vi.fn(),
} as unknown as DescribeRunProgress;

const baseProps = {
  selectedCount: 2,
  isSubmitting: false,
  isCancelling: false,
  isRunning: false,
  runId: null as string | null,
  progress: idleProgress,
  isPanelVisible: false,
  errorMessage: null as string | null,
  onSubmit: vi.fn(),
  onCancel: vi.fn(),
  onDismiss: vi.fn(),
  onRetryPolling: vi.fn(),
};

const describedTargets = (button: HTMLElement): HTMLElement[] => {
  const ids = (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
  return ids
    .map((id) => document.getElementById(id))
    .filter((node): node is HTMLElement => node !== null);
};

describe('BulkDescribeCta recognition disclosure (HAI-04 / HAI-05 / RLSE-04)', () => {
  it('labels the primary with the selected count', () => {
    render(<BulkDescribeCta {...baseProps} selectedCount={3} recognitionEnabled />);

    expect(screen.getByRole('button', { name: 'Describe 3 selected' })).toBeInTheDocument();
  });

  it('discloses ON wording, credits, and a Settings off-ramp when recognition is known on', () => {
    render(<BulkDescribeCta {...baseProps} selectedCount={12} recognitionEnabled />);

    const disclosure = screen.getByText(/Identifies people first \(AI\)/);
    expect(disclosure).toHaveTextContent('Identifies people first (AI) · ~12 credits · Turn off in Settings');
    const settings = screen.getByRole('link', { name: 'Settings' });
    expect(settings).toHaveAttribute('href', '#/settings');
    expect(disclosure).toContainElement(settings);
  });

  it('discloses OFF wording and credits without a Settings link when recognition is known off', () => {
    render(<BulkDescribeCta {...baseProps} selectedCount={4} recognitionEnabled={false} />);

    expect(
      screen.getByText('People are not identified (recognition off) · ~4 credits'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument();
  });

  it('ties the primary to the disclosure via aria-describedby', () => {
    render(<BulkDescribeCta {...baseProps} recognitionEnabled />);

    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
    const targets = describedTargets(button);
    expect(targets.length).toBeGreaterThan(0);
    expect(targets.some((node) => node.textContent?.includes('Identifies people first (AI)'))).toBe(
      true,
    );
  });

  it('renders OFF wording without a Settings link while recognition is unknown', () => {
    render(<BulkDescribeCta {...baseProps} selectedCount={2} />);

    expect(
      screen.getByText('People are not identified (recognition off) · ~2 credits'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument();
  });
});
