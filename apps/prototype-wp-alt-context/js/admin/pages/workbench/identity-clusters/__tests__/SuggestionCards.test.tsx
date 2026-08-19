import React from 'react';
import { render, screen } from '@testing-library/react';
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
