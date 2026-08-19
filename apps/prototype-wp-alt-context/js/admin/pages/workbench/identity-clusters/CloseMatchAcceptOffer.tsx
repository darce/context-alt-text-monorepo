/**
 * UXW2-6 slice 3 — offer to also accept a review group's close matches.
 * Preview count only; writes happen after the operator confirms.
 */

import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../../components/ui/dialog';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';
import { REVIEW_GROUP_ACCEPT_CAP } from './reviewQueueDriver';

export const CLOSE_MATCH_OFFER_COPY = {
  TITLE: __('Accept close matches?', 'alt-context'),
  CONFIRM: __('Accept close matches', 'alt-context'),
  SKIP: __('Just this one', 'alt-context'),
  TRUNCATION: __(
    'Accepting the first %1$d close matches. %2$d more were not included.',
    'alt-context',
  ),
} as const;

export const closeMatchOfferDescription = (count: number): string =>
  sprintf(
    _n(
      'Also accept %d close match?',
      'Also accept %d close matches?',
      count,
      'alt-context',
    ),
    count,
  );

export const closeMatchAcceptedAnnouncement = (accepted: number, omitted: number): string => {
  const saved = sprintf(
    _n('Accepted %d close match.', 'Accepted %d close matches.', accepted, 'alt-context'),
    accepted,
  );
  if (omitted <= 0) {
    return saved;
  }
  return `${saved} ${sprintf(__('%d more were not included.', 'alt-context'), omitted)}`;
};

export interface CloseMatchAcceptOfferProps {
  open: boolean;
  count: number;
  omitted: number;
  truncated: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  onSkip: () => void;
  accentPrimary?: boolean;
}

export const CloseMatchAcceptOffer = ({
  open,
  count,
  omitted,
  truncated,
  onOpenChange,
  onConfirm,
  onSkip,
  accentPrimary = false,
}: CloseMatchAcceptOfferProps): React.JSX.Element | null => {
  const confirmRef = React.useRef<HTMLButtonElement>(null);
  if (count <= 0) {
    return null;
  }

  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogContent
          className="acx-close-match-offer"
          aria-describedby="acx-close-match-offer-desc"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            confirmRef.current?.focus();
          }}
        >
          <DialogTitle>{CLOSE_MATCH_OFFER_COPY.TITLE}</DialogTitle>
          <DialogDescription id="acx-close-match-offer-desc">
            {closeMatchOfferDescription(count)}
          </DialogDescription>
          {truncated ? (
            <p className="acx-close-match-offer__truncation" role="status">
              {sprintf(CLOSE_MATCH_OFFER_COPY.TRUNCATION, REVIEW_GROUP_ACCEPT_CAP, omitted)}
            </p>
          ) : null}
          <div className="acx-dialog__actions">
            <button
              type="button"
              className="button acx-close-match-offer__skip"
              onClick={onSkip}
            >
              {CLOSE_MATCH_OFFER_COPY.SKIP}
            </button>
            <button
              ref={confirmRef}
              type="button"
              className={
                accentPrimary
                  ? 'button button-primary acx-close-match-offer__confirm acx-accent-primary-action'
                  : 'button button-primary acx-close-match-offer__confirm'
              }
              {...(accentPrimary ? { [ACCENT_PRIMARY_ATTR]: true } : {})}
              onClick={onConfirm}
            >
              {CLOSE_MATCH_OFFER_COPY.CONFIRM}
            </button>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};
