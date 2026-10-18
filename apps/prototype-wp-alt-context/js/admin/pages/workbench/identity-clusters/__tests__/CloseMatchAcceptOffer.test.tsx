import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ACCENT_PRIMARY_ATTR } from '../../mediaFooterCtaState';
import {
  CLOSE_MATCH_OFFER_COPY,
  CloseMatchAcceptOffer,
  closeMatchAcceptedAnnouncement,
  closeMatchOfferDescription,
} from '../CloseMatchAcceptOffer';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

describe('CloseMatchAcceptOffer (UXW2-6 slice 3)', () => {
  it('shows the close-match count before any write and uses the canonical term', () => {
    const onConfirm = vi.fn();
    render(
      <CloseMatchAcceptOffer
        open
        count={3}
        omitted={0}
        truncated={false}
        onOpenChange={vi.fn()}
        onConfirm={onConfirm}
        onSkip={vi.fn()}
        accentPrimary
      />,
    );

    expect(screen.getByRole('dialog', { name: CLOSE_MATCH_OFFER_COPY.TITLE })).toBeInTheDocument();
    expect(screen.getByText(closeMatchOfferDescription(3))).toBeInTheDocument();
    expect(screen.getByText(closeMatchOfferDescription(3))).toHaveTextContent('close matches');
    expect(screen.queryByText(/were not included/)).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('surfaces an explicit truncation signal when more than 25 qualify', () => {
    render(
      <CloseMatchAcceptOffer
        open
        count={25}
        omitted={4}
        truncated
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        onSkip={vi.fn()}
        accentPrimary
      />,
    );

    expect(
      screen.getByText('Accepting the first 25 close matches. 4 more were not included.'),
    ).toBeInTheDocument();
  });

  it('renders nothing when count is zero', () => {
    const { container } = render(
      <CloseMatchAcceptOffer
        open
        count={0}
        omitted={0}
        truncated={false}
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        onSkip={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByText(/0 close match/)).not.toBeInTheDocument();
  });

  it('keeps a single accent primary on the confirm control', () => {
    render(
      <CloseMatchAcceptOffer
        open
        count={2}
        omitted={0}
        truncated={false}
        onOpenChange={vi.fn()}
        onConfirm={vi.fn()}
        onSkip={vi.fn()}
        accentPrimary
      />,
    );

    const marked = document.querySelectorAll(`[${ACCENT_PRIMARY_ATTR}]`);
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveAccessibleName(CLOSE_MATCH_OFFER_COPY.CONFIRM);
  });

  it('confirm and skip call the matching callbacks; Esc uses onOpenChange', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onSkip = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <CloseMatchAcceptOffer
        open
        count={2}
        omitted={0}
        truncated={false}
        onOpenChange={onOpenChange}
        onConfirm={onConfirm}
        onSkip={onSkip}
        accentPrimary
      />,
    );

    await user.click(screen.getByRole('button', { name: CLOSE_MATCH_OFFER_COPY.CONFIRM }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: CLOSE_MATCH_OFFER_COPY.SKIP }));
    expect(onSkip).toHaveBeenCalledTimes(1);

    await user.keyboard('{Escape}');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('announces accepted close matches without banned soft fillers or invented counts', () => {
    expect(closeMatchAcceptedAnnouncement(1, 0)).toBe('Accepted 1 close match.');
    expect(closeMatchAcceptedAnnouncement(4, 0)).toBe('Accepted 4 close matches.');
    expect(closeMatchAcceptedAnnouncement(25, 3)).toBe(
      'Accepted 25 close matches. 3 more were not included.',
    );
    expect(closeMatchAcceptedAnnouncement(4, 0)).not.toMatch(/some|several|a few|failed to save/i);
  });
});
