import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ReviewSuggestion } from '../suggestionReviewItems';
import { SuggestionCard } from '../SuggestionCards';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

// Radix Avatar's Image gates on Image.onload, which never fires in JSDOM.
vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

const baseSuggestion: ReviewSuggestion = {
  suggestionId: 'sugg-1',
  identityId: 'identity-1',
  clusterId: 'cluster-1',
  label: 'Alex',
  similarity: 0.9,
  identityCount: 3,
};

describe('SuggestionCard BR-41 group accname', () => {
  it.each([
    { label: '1 of 2', queuePosition: 1, queueTotal: 2 },
    { label: '3 of 3', queuePosition: 3, queueTotal: 3 },
    { label: '1 of 1', queuePosition: 1, queueTotal: 1 },
  ])(
    'card root has Face suggestion $label when ordinal pair valid',
    ({ queuePosition, queueTotal }) => {
      render(
        <SuggestionCard
          suggestion={{ ...baseSuggestion, suggestionId: `sugg-${queuePosition}-${queueTotal}` }}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          isPending={false}
          lowConfidenceThreshold={0.5}
          queuePosition={queuePosition}
          queueTotal={queueTotal}
        />,
      );

      const card = screen.getByTestId('acx-review-card');
      expect(card).toHaveAttribute('role', 'group');
      expect(card).toHaveAccessibleName(
        new RegExp(`Face suggestion ${queuePosition} of ${queueTotal}`),
      );
    },
  );

  it.each([
    { label: 'total=0', queuePosition: 1, queueTotal: 0 },
    { label: 'position=NaN', queuePosition: Number.NaN, queueTotal: 2 },
    { label: 'total=Infinity', queuePosition: 1, queueTotal: Number.POSITIVE_INFINITY },
    { label: 'position=float', queuePosition: 1.5, queueTotal: 2 },
    { label: 'position>total', queuePosition: 4, queueTotal: 3 },
  ])(
    'BR-41: invalid queue ordinals fall back to kind-only Face suggestion — $label',
    ({ label, queuePosition, queueTotal }) => {
      render(
        <SuggestionCard
          suggestion={{ ...baseSuggestion, suggestionId: `sugg-${label}` }}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          isPending={false}
          lowConfidenceThreshold={0.5}
          queuePosition={queuePosition}
          queueTotal={queueTotal}
        />,
      );

      const card = screen.getByTestId('acx-review-card');
      expect(card, label).toHaveAccessibleName('Face suggestion');
      expect(card, label).not.toHaveAccessibleName(/of 0|NaN|Infinity|1\.5|4 of 3/i);
    },
  );

  it('BR-41: without queuePosition/queueTotal, accname is kind-only Face suggestion (never empty)', () => {
    render(
      <SuggestionCard
        suggestion={baseSuggestion}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    const card = screen.getByTestId('acx-review-card');
    expect(card).toHaveAccessibleName('Face suggestion');
    expect(screen.queryByText(/Face suggestion \d+ of \d+/)).toBeNull();
  });

  it('Yes fires onAccept once and does not preview a close-match group on the card', async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={baseSuggestion}
        onAccept={onAccept}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Yes' }));
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText(/close matches/i)).not.toBeInTheDocument();
  });

  it('renders the face-count string and review title (UXW2-3-R1-11)', () => {
    render(
      <SuggestionCard
        suggestion={baseSuggestion}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onReview={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    expect(screen.getByText(/3 faces/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review details' })).toHaveAttribute(
      'title',
      'Review these faces',
    );
  });
});

describe('SuggestionCard lightbox target (UXW2-6)', () => {
  it('passes identity media id and face id when opening the candidate original', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          identityId: 'identity-1',
          enrichment: {
            identityMediaId: 42,
            identityMediaUrl: 'https://example.com/candidate.jpg',
            identityBbox: { x: 5, y: 6, width: 40, height: 50 },
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'View original photo' }));
    expect(onOpenOriginal).toHaveBeenCalledWith({
      mediaUrl: 'https://example.com/candidate.jpg',
      bbox: { x: 5, y: 6, width: 40, height: 50 },
      label: 'Candidate face',
      mediaId: 42,
      identityId: 'identity-1',
    });
  });

  it('omits mediaId when the candidate media id is missing so the lightbox does not fetch', async () => {
    const onOpenOriginal = vi.fn();
    const user = userEvent.setup();
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          identityId: 'identity-1',
          enrichment: {
            identityMediaUrl: 'https://example.com/candidate.jpg',
            identityBbox: { x: 5, y: 6, width: 40, height: 50 },
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        onOpenOriginal={onOpenOriginal}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'View original photo' }));
    expect(onOpenOriginal).toHaveBeenCalledWith({
      mediaUrl: 'https://example.com/candidate.jpg',
      bbox: { x: 5, y: 6, width: 40, height: 50 },
      label: 'Candidate face',
      identityId: 'identity-1',
    });
    expect(onOpenOriginal.mock.calls[0][0]).not.toHaveProperty('mediaId');
  });
});

describe('SuggestionCard L4R-01 Avatar alt + L4R-02 assertTruthyLabel', () => {
  it('L4R-01: Avatar representative branch img alt equals person displayLabel', () => {
    // Predicted first failure: alt is generic "Cluster representative" (pre-displayLabel change).
    render(
      <SuggestionCard
        suggestion={{
          ...baseSuggestion,
          label: 'Jordan Lee',
          enrichment: {
            representativeThumbUrl: 'https://example.com/rep-thumb.jpg',
          },
        }}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
      />,
    );

    const repImg = screen.getByAltText('Jordan Lee');
    expect(repImg).toHaveAttribute('src', 'https://example.com/rep-thumb.jpg');
    expect(screen.queryByAltText('Cluster representative')).toBeNull();
  });

  it('L4R-02: assertTruthyLabel throws for whitespace-only label', () => {
    // Predicted first failure: whitespace-only label accepted (length>0 without trim).
    expect(() =>
      render(
        <SuggestionCard
          suggestion={{ ...baseSuggestion, label: ' ' }}
          onAccept={vi.fn()}
          onReject={vi.fn()}
          isPending={false}
          lowConfidenceThreshold={0.5}
        />,
      ),
    ).toThrow('SuggestionCard requires a truthy suggestion.label');
  });
});
