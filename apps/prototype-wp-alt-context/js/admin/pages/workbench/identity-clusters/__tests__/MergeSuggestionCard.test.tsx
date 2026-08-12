import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { MergeSuggestionCard } from '../MergeSuggestionCard';
import type { PendingMergeSuggestion } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const FACE_BBOX = { x: 10, y: 20, width: 80, height: 90 };

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

const withFaces = (overrides: Partial<PendingMergeSuggestion> = {}): PendingMergeSuggestion => ({
  ...baseSuggestion,
  cluster_a_representative_media_url: 'http://example.test/a.jpg',
  cluster_a_representative_bbox: FACE_BBOX,
  cluster_b_representative_media_url: 'http://example.test/b.jpg',
  cluster_b_representative_bbox: FACE_BBOX,
  ...overrides,
});

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

  // FIX-1 / A11Y-02 / HAI-01: auto cluster-* must not name a face on screen or in alt.
  it('gates auto cluster-* labels to Unnamed cluster / Detected face alt', () => {
    const { container } = render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: 'cluster-7',
          cluster_b_label: 'cluster-9',
          cluster_a_identity_count: 2,
          cluster_b_identity_count: 5,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
      />,
    );

    expect(container.textContent).not.toContain('cluster-7');
    expect(container.textContent).not.toContain('cluster-9');
    expect(screen.queryByAltText('cluster-7')).toBeNull();
    expect(screen.queryByAltText('cluster-9')).toBeNull();
    expect(screen.getAllByAltText('Detected face')).toHaveLength(2);
    expect(screen.getByText('Unnamed cluster (2)')).toBeInTheDocument();
    expect(screen.getByText('Unnamed cluster (5)')).toBeInTheDocument();
  });

  // Discriminates isHumanLabeledTarget (trims) from isMeaningfulMergeLabel (no trim).
  it('gates whitespace-padded cluster-* the same as bare auto-labels', () => {
    const { container } = render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: '  cluster-7',
          cluster_b_label: 'cluster-9',
          cluster_a_identity_count: 3,
          cluster_b_identity_count: 4,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
      />,
    );

    expect(container.textContent).not.toContain('cluster-7');
    expect(screen.queryByAltText('cluster-7')).toBeNull();
    expect(screen.queryByAltText('  cluster-7')).toBeNull();
    expect(screen.getAllByAltText('Detected face')).toHaveLength(2);
    expect(screen.getByText('Unnamed cluster (3)')).toBeInTheDocument();
  });

  it('keeps human labels as visible text and crop alt with identity count', () => {
    render(
      <MergeSuggestionCard
        suggestion={withFaces({
          cluster_a_label: 'Ada Lovelace',
          cluster_b_label: 'Jordan',
          cluster_a_identity_count: 3,
          cluster_b_identity_count: 4,
        })}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
      />,
    );

    expect(screen.getByText('Ada Lovelace (3)')).toBeInTheDocument();
    expect(screen.getByAltText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByText('Jordan (4)')).toBeInTheDocument();
    expect(screen.getByAltText('Jordan')).toBeInTheDocument();
  });
});
