import type { RosterEntry } from '../../api/rosterApi';

/**
 * Canonical person states for the roster table [sr-007].
 * Mutually exclusive and collectively exhaustive [NAV-05].
 *
 * Derivation uses only contract fields from RosterEntry: `name` and
 * `queue_memberships`. `projection_status` is a separate axis and is not folded in.
 */
export const PERSON_STATES = {
  NEEDS_REVIEW: 'needs-review',
  UNNAMED: 'unnamed',
  NAMED: 'named',
} as const;

export type PersonState = (typeof PERSON_STATES)[keyof typeof PERSON_STATES];

/**
 * Derive exactly one person state from a roster entry.
 *
 * Precedence (load-bearing): needs-review > unnamed > named.
 * A queue membership is a system-raised request with its own resolution path;
 * naming does not clear it. Blank name + non-empty queue_memberships → needs-review.
 */
export const derivePersonState = (entry: RosterEntry): PersonState => {
  if (entry.queue_memberships.length > 0) {
    return PERSON_STATES.NEEDS_REVIEW;
  }

  if (entry.name.trim() === '') {
    return PERSON_STATES.UNNAMED;
  }

  return PERSON_STATES.NAMED;
};
