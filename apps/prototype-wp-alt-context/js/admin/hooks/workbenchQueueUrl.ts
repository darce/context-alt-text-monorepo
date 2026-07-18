/**
 * E21-5 Slice 1b — `rq=` URL param encoding for the review queue.
 *
 * Encoding (pinned): `rq=<kind>.<band>.<index>`
 *   kind ∈ {all, assignment, merge}
 *   band ∈ {all, strong, weaker}  (always `all` in 1b)
 *   index ≥ 0 integer
 *
 * Omitted-as-defaults; malformed → defaults (never crash).
 */

import {
  REVIEW_QUEUE_FILTER,
  type ReviewQueueFilter,
} from '../pages/workbench/identity-clusters/reviewQueueDriver';

export const REVIEW_QUEUE_KIND_PARAM = {
  ALL: 'all',
  ASSIGNMENT: 'assignment',
  MERGE: 'merge',
} as const;

export type ReviewQueueKindParam =
  (typeof REVIEW_QUEUE_KIND_PARAM)[keyof typeof REVIEW_QUEUE_KIND_PARAM];

export const REVIEW_QUEUE_BAND_PARAM = {
  ALL: 'all',
  STRONG: 'strong',
  WEAKER: 'weaker',
} as const;

export type ReviewQueueBandParam =
  (typeof REVIEW_QUEUE_BAND_PARAM)[keyof typeof REVIEW_QUEUE_BAND_PARAM];

export interface WorkbenchQueueState {
  kind: ReviewQueueKindParam;
  band: ReviewQueueBandParam;
  index: number;
}

export const DEFAULT_QUEUE_STATE: WorkbenchQueueState = {
  kind: REVIEW_QUEUE_KIND_PARAM.ALL,
  band: REVIEW_QUEUE_BAND_PARAM.ALL,
  index: 0,
};

const KIND_SET: ReadonlySet<string> = new Set(Object.values(REVIEW_QUEUE_KIND_PARAM));
const BAND_SET: ReadonlySet<string> = new Set(Object.values(REVIEW_QUEUE_BAND_PARAM));

/** Parse `rq` search param; malformed → defaults (never throws). */
export const parseQueueState = (raw: string | null | undefined): WorkbenchQueueState => {
  if (raw == null || raw === '') {
    return { ...DEFAULT_QUEUE_STATE };
  }

  const parts = raw.split('.');
  if (parts.length !== 3) {
    return { ...DEFAULT_QUEUE_STATE };
  }

  const [kindRaw, bandRaw, indexRaw] = parts;
  if (!KIND_SET.has(kindRaw) || !BAND_SET.has(bandRaw)) {
    return { ...DEFAULT_QUEUE_STATE };
  }

  // Reject non-canonical integers (leading zeros, floats, signs).
  // "0" is valid; "01" / "00" are not.
  if (!/^(0|[1-9]\d*)$/.test(indexRaw)) {
    return { ...DEFAULT_QUEUE_STATE };
  }
  const index = Number.parseInt(indexRaw, 10);
  if (!Number.isFinite(index) || index < 0) {
    return { ...DEFAULT_QUEUE_STATE };
  }

  return {
    kind: kindRaw as ReviewQueueKindParam,
    band: bandRaw as ReviewQueueBandParam,
    index,
  };
};

/** Serialize; returns null when fully default so callers can omit the param. */
export const serializeQueueState = (state: WorkbenchQueueState): string | null => {
  if (
    state.kind === DEFAULT_QUEUE_STATE.kind &&
    state.band === DEFAULT_QUEUE_STATE.band &&
    state.index === DEFAULT_QUEUE_STATE.index
  ) {
    return null;
  }
  return `${state.kind}.${state.band}.${state.index}`;
};

/** Map URL kind param → driver filter (sr-007). */
export const kindParamToFilter = (kind: ReviewQueueKindParam): ReviewQueueFilter => {
  switch (kind) {
    case REVIEW_QUEUE_KIND_PARAM.ASSIGNMENT:
      return REVIEW_QUEUE_FILTER.ASSIGNMENT;
    case REVIEW_QUEUE_KIND_PARAM.MERGE:
      return REVIEW_QUEUE_FILTER.MERGE;
    default:
      return REVIEW_QUEUE_FILTER.ALL;
  }
};

/** Map driver filter → URL kind param. */
export const filterToKindParam = (filter: ReviewQueueFilter): ReviewQueueKindParam => {
  switch (filter) {
    case REVIEW_QUEUE_FILTER.ASSIGNMENT:
      return REVIEW_QUEUE_KIND_PARAM.ASSIGNMENT;
    case REVIEW_QUEUE_FILTER.MERGE:
      return REVIEW_QUEUE_KIND_PARAM.MERGE;
    default:
      return REVIEW_QUEUE_KIND_PARAM.ALL;
  }
};
