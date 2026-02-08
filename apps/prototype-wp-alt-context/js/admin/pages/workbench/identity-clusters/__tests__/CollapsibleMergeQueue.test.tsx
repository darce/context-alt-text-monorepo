import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CollapsibleMergeQueue } from '../CollapsibleMergeQueue';
import type { PendingMergeSuggestion } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const suggestion: PendingMergeSuggestion = {
  id: 'merge-1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.78,
  status: 'pending',
  cluster_a_label: 'Alex',
  cluster_b_label: 'Jordan',
};

describe('CollapsibleMergeQueue', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('returns null when there are no suggestions', () => {
    const { container } = render(
      <CollapsibleMergeQueue suggestions={[]} onAccept={vi.fn()} onReject={vi.fn()} isPending={false} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders and toggles merge suggestions', async () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();
    const user = userEvent.setup();

    render(
      <CollapsibleMergeQueue suggestions={[suggestion]} onAccept={onAccept} onReject={onReject} isPending={false} />,
    );

    expect(screen.getByText('Merge Candidates')).toBeInTheDocument();
    expect(screen.queryByText('Are these the same person?')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Merge Candidates/i }));
    expect(screen.getByText('Are these the same person?')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Yes' }));
    await user.click(screen.getByRole('button', { name: 'No' }));

    expect(onAccept).toHaveBeenCalledWith('merge-1');
    expect(onReject).toHaveBeenCalledWith('merge-1');
  });

  it('restores open state from localStorage', () => {
    window.localStorage.setItem('AltContext:MergeQueue:Open', 'true');

    render(
      <CollapsibleMergeQueue suggestions={[suggestion]} onAccept={vi.fn()} onReject={vi.fn()} isPending={false} />,
    );

    expect(screen.getByText('Are these the same person?')).toBeInTheDocument();
  });
});
