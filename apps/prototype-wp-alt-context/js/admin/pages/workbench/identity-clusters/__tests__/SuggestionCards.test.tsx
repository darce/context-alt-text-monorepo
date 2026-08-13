import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ReviewSuggestion } from '../suggestionReviewItems';
import { SuggestionCard } from '../SuggestionCards';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

const baseSuggestion: ReviewSuggestion = {
  suggestionId: 'sugg-1',
  identityId: 'identity-1',
  clusterId: 'cluster-1',
  label: 'Alex',
  similarity: 0.9,
  identityCount: 3,
};

describe('SuggestionCard BR-41 group accname', () => {
  it('card root has Face suggestion 1 of 2 when ordinal valid', () => {
    render(
      <SuggestionCard
        suggestion={baseSuggestion}
        onAccept={vi.fn()}
        onReject={vi.fn()}
        isPending={false}
        lowConfidenceThreshold={0.5}
        queuePosition={1}
        queueTotal={2}
      />,
    );

    const card = screen.getByTestId('acx-review-card');
    expect(card).toHaveAttribute('role', 'group');
    expect(card).toHaveAccessibleName(/Face suggestion 1 of 2/);
  });

  it.each([
    { label: 'total=0', queuePosition: 1, queueTotal: 0 },
    { label: 'position=NaN', queuePosition: Number.NaN, queueTotal: 2 },
    { label: 'total=Infinity', queuePosition: 1, queueTotal: Number.POSITIVE_INFINITY },
    { label: 'position=float', queuePosition: 1.5, queueTotal: 2 },
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
      expect(card, label).not.toHaveAccessibleName(/of 0|NaN|Infinity|1\.5/i);
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
});
