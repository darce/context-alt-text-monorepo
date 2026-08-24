/**
 * Shared empty-state primitive (DEMO-UX-1-D-6).
 *
 * Two rules are enforced by the type, not by reviewer vigilance:
 *
 * 1. [NAV-08] An `action` is REQUIRED, and it must actually do something
 *    (`onClick` or `href`). A zero result that offers no way forward is a dead
 *    end; this component cannot express one.
 * 2. ZERO is not BROKEN. `variant` forces the caller to say which it is.
 *    `empty` means "nothing here yet, here is the front door". `unavailable`
 *    means "we could not load this, here is retry". Flattening the second into
 *    the first tells the operator the backlog is clear while the queue is down
 *    — the failure the shipped string 'Face assignments unavailable — this is
 *    not an empty backlog.' was written to prevent.
 *
 * [COG-01] Heading and body copy come from the caller and must be
 * outcome-worded ("No findings yet — run a scan"), never operator-worded
 * ("query returned 0 rows").
 */

import * as React from 'react';
import { __ } from '@wordpress/i18n';
import { AlertTriangle, Inbox } from 'lucide-react';

/** [sr-007] Single canonical source for the variant values. */
export const EmptyStateVariant = {
  EMPTY: 'empty',
  UNAVAILABLE: 'unavailable',
} as const;

export type EmptyStateVariantValue = (typeof EmptyStateVariant)[keyof typeof EmptyStateVariant];

/** Derived from the as-const object so the list can never drift from it [sr-007]. */
export const EMPTY_STATE_VARIANTS = Object.values(EmptyStateVariant);

/**
 * The way out. A bare label is not a way out, so the union requires exactly one
 * of `onClick` (in-place recovery / front door) or `href` (another screen).
 */
export type EmptyStateAction =
  | { label: string; onClick: () => void; busy?: boolean; href?: never }
  | { label: string; href: string; onClick?: never };

export interface EmptyStateProps {
  variant: EmptyStateVariantValue;
  /** Outcome-worded, one line. Names the state in the operator's own goal terms [COG-01]. */
  heading: string;
  /** What to do next, in plain language [NAV-08]. */
  body: string;
  /** Required: the front door out of the dead end [NAV-08]. */
  action: EmptyStateAction;
  /** Optional transition announcement for an empty state whose host previously announced completion. */
  announcement?: string;
  /** Disable the internal live region when the host already owns the page's status channel. */
  announceState?: boolean;
  /** Keeps the host surface's heading outline valid [A11Y-24]. */
  headingLevel?: 2 | 3 | 4;
  className?: string;
  /**
   * In-page landing after the front door fires (e.g. move focus). Does not
   * replace `action.href` / `action.onClick` — those remain the exclusive way
   * out [NAV-08].
   */
  onActivate?: () => void;
}

const HEADING_TAGS = {
  2: 'h2',
  3: 'h3',
  4: 'h4',
} as const;

/**
 * [sr-004] The glyph is the non-colour half of the status signal; the two
 * variants must never differ by colour alone.
 */
const VARIANT_ICONS = {
  [EmptyStateVariant.EMPTY]: { Glyph: Inbox, name: 'inbox' },
  [EmptyStateVariant.UNAVAILABLE]: { Glyph: AlertTriangle, name: 'alert-triangle' },
} as const;

export const EmptyState: React.FC<EmptyStateProps> = ({
  variant,
  heading,
  body,
  action,
  announcement: announcementText = '',
  announceState = true,
  headingLevel = 3,
  className,
  onActivate,
}) => {
  const headingId = React.useId();
  const Heading = HEADING_TAGS[headingLevel];
  const { Glyph, name: iconName } = VARIANT_ICONS[variant];
  const isUnavailable = variant === EmptyStateVariant.UNAVAILABLE;
  const [announcement, setAnnouncement] = React.useState('');

  // The glyph is aria-hidden, so the state needs a text equivalent [A11Y-24].
  // Literals (not a lookup table) so wp i18n string extraction sees them [RLSE-04].
  const statusLabel = isUnavailable ? __('Could not load', 'alt-context') : __('Nothing here yet', 'alt-context');

  React.useEffect(() => {
    setAnnouncement(isUnavailable ? statusLabel : announcementText);
  }, [announcementText, isUnavailable, statusLabel]);

  const classNames = ['acx-empty-state', `acx-empty-state--${variant}`, className].filter(Boolean).join(' ');

  return (
    <section className={classNames} data-testid="acx-empty-state" data-variant={variant} aria-labelledby={headingId}>
      {announceState ? (
        <div className="screen-reader-text" role="status" aria-live="polite" data-testid="acx-empty-state-live-region">
          {announcement}
        </div>
      ) : null}
      <span
        className="acx-empty-state__icon"
        data-testid="acx-empty-state-icon"
        data-icon={iconName}
        aria-hidden="true"
      >
        <Glyph />
      </span>
      <span className="screen-reader-text" data-testid="acx-empty-state-status-label">
        {statusLabel}
      </span>
      <div className="acx-empty-state__content">
        <Heading id={headingId} className="acx-empty-state__heading">
          {heading}
        </Heading>
        <p className="acx-empty-state__body">{body}</p>
        <div className="acx-empty-state__action">
          {action.href !== undefined ? (
            <a
              className="acx-empty-state__action-control"
              href={action.href}
              onClick={() => onActivate?.()}
            >
              {action.label}
            </a>
          ) : (
            <button
              type="button"
              className="acx-empty-state__action-control"
              onClick={() => {
                action.onClick();
                onActivate?.();
              }}
              aria-busy={action.busy ? 'true' : undefined}
            >
              {action.label}
            </button>
          )}
        </div>
      </div>
    </section>
  );
};

EmptyState.displayName = 'EmptyState';
