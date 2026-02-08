import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { MergeSuggestionCard } from '../MergeSuggestionCard';
import type { PendingMergeSuggestion } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const baseSuggestion: PendingMergeSuggestion = {
  id: 'merge-1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.87,
  status: 'pending',
  cluster_a_label: 'Alex',
  cluster_b_label: 'Jordan',
  cluster_a_identity_count: 3,
  cluster_b_identity_count: 4,
};

describe('MergeSuggestionCard', () => {
  it('renders labels and similarity for merge review', () => {
    render(<MergeSuggestionCard suggestion={baseSuggestion} onAccept={vi.fn()} onReject={vi.fn()} isPending={false} />);

    expect(screen.getByText('Are these the same person?')).toBeInTheDocument();
    expect(screen.getByText('87% match')).toBeInTheDocument();
    expect(screen.getByText('Alex (3)')).toBeInTheDocument();
    expect(screen.getByText('Jordan (4)')).toBeInTheDocument();
  });

  it('disables actions while pending and calls handlers when active', async () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();

    const { rerender } = render(
      <MergeSuggestionCard suggestion={baseSuggestion} onAccept={onAccept} onReject={onReject} isPending={true} />,
    );

    expect(screen.getByRole('button', { name: 'Yes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'No' })).toBeDisabled();

    rerender(
      <MergeSuggestionCard suggestion={baseSuggestion} onAccept={onAccept} onReject={onReject} isPending={false} />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Yes' }));
    await user.click(screen.getByRole('button', { name: 'No' }));

    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });
});
