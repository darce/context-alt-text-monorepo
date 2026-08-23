import { __ } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';
import { APP_LINK_PARAMS, toWorkbench } from '../../navigation/appLinks';
import { DEFAULT_QUEUE_STATE } from '../../hooks/workbenchQueueUrl';

/**
 * E21-9 Slice 5a + E21-10 Slice 4 (lands-second): Clusters tab retired; getLegacyTab gone.
 * People is the only roster surface. `tab=*` is ignored (no rewrite). `cluster=` opens the
 * person-first drawer in place — not a Clusters-tab selector (that grammar is retired).
 */
export const ROSTER_SURFACE = {
  id: 'people' as const,
  label: __('People', 'alt-context'),
} as const;

/** @deprecated Use ROSTER_SURFACE — kept as a named export only for migration grep tests. */
export type RosterTab = never;

export const ROSTER_ROUTE_PARAM_KEYS = ['person', 'queue', 'face', 'cluster'] as const;

export interface ParsedRosterRoute {
  selectedClusterId: string | null;
  selectedFaceId: string | null;
  requiresProjectionGateNotice: boolean;
}

export type ProjectionStatus = RosterEntry['projection_status'];

const PROJECTION_STATUSES = new Set<ProjectionStatus>(['current', 'refreshing', 'stale', 'failed']);

const PROJECTION_PRIORITY: Record<ProjectionStatus, number> = {
  failed: 3,
  stale: 2,
  refreshing: 1,
  current: 0,
};

export const getRouteParam = (searchParams: URLSearchParams, key: string): string | null => {
  const value = searchParams.get(key)?.trim();
  if (!value) {
    return null;
  }
  return value;
};

// Tolerate fixtures and legacy callers that omit the canonical RCL-004 fields by treating
// missing/non-string values as 'no projection'. Strict typecheck handles new code paths.
export const getEntryProjectionStatus = (entry: RosterEntry): ProjectionStatus | null => {
  const raw: unknown = entry.projection_status;
  if (typeof raw !== 'string') {
    return null;
  }
  return PROJECTION_STATUSES.has(raw as ProjectionStatus) ? (raw as ProjectionStatus) : null;
};

export const getEntryPersonUuid = (entry: RosterEntry): string | null => {
  const raw: unknown = entry.person_uuid;
  return typeof raw === 'string' && raw.length > 0 ? raw : null;
};

const DETERMINISTIC_COMPARE_LOCALE = 'en';
const DETERMINISTIC_COMPARE_OPTIONS = { sensitivity: 'base' } as const;

const getSortableEntryName = (entry: RosterEntry): string => entry.name.trim().toLowerCase();

export const selectDeterministicDefaultWorkspaceEntry = (entries: readonly RosterEntry[]): RosterEntry | null => {
  const candidates = entries.filter((entry) => getEntryPersonUuid(entry) !== null);
  if (candidates.length === 0) {
    return null;
  }

  return (
    [...candidates].sort((left, right) => {
      const nameComparison = getSortableEntryName(left).localeCompare(
        getSortableEntryName(right),
        DETERMINISTIC_COMPARE_LOCALE,
        DETERMINISTIC_COMPARE_OPTIONS,
      );
      if (nameComparison !== 0) {
        return nameComparison;
      }

      const leftPersonUuid = getEntryPersonUuid(left) ?? '';
      const rightPersonUuid = getEntryPersonUuid(right) ?? '';
      const personComparison = leftPersonUuid.localeCompare(
        rightPersonUuid,
        DETERMINISTIC_COMPARE_LOCALE,
        DETERMINISTIC_COMPARE_OPTIONS,
      );
      if (personComparison !== 0) {
        return personComparison;
      }

      return left.id - right.id;
    })[0] ?? null
  );
};

/**
 * Parse roster search params on the single person-first surface.
 * - `tab` is ignored (legacy `tab=clusters` bookmarks land on the page).
 * - `cluster=<id>` opens the drawer in place.
 * - person/queue/face keep projection-gate notice behavior.
 */
export const parseRosterRoute = (searchParams: URLSearchParams): ParsedRosterRoute => {
  const selectedFaceId = getRouteParam(searchParams, 'face');

  if (
    getRouteParam(searchParams, 'person') ||
    getRouteParam(searchParams, 'queue') ||
    selectedFaceId
  ) {
    return {
      selectedClusterId: null,
      selectedFaceId,
      requiresProjectionGateNotice: true,
    };
  }

  const clusterId = getRouteParam(searchParams, 'cluster');
  if (clusterId) {
    return {
      selectedClusterId: clusterId,
      selectedFaceId: null,
      requiresProjectionGateNotice: false,
    };
  }

  return {
    selectedClusterId: null,
    selectedFaceId: null,
    requiresProjectionGateNotice: false,
  };
};

export const writeRosterFaceParam = (
  previous: URLSearchParams,
  faceId: string | null,
  personUuid?: string | null,
): URLSearchParams => {
  const next = new URLSearchParams(previous);
  if (typeof personUuid === 'string' && personUuid.length > 0) {
    next.set('person', personUuid);
  }
  if (typeof faceId === 'string' && faceId.length > 0) {
    next.set('face', faceId);
  } else {
    next.delete('face');
  }
  return next;
};

export const hasCanonicalProjectionShape = (entries: readonly RosterEntry[]): boolean =>
  entries.some((entry) => getEntryPersonUuid(entry) !== null && getEntryProjectionStatus(entry) !== null);

export const aggregateProjectionStatus = (entries: readonly RosterEntry[]): ProjectionStatus | null => {
  let aggregate: ProjectionStatus | null = null;
  for (const entry of entries) {
    const status = getEntryProjectionStatus(entry);
    if (status === null) {
      continue;
    }
    if (aggregate === null || PROJECTION_PRIORITY[status] > PROJECTION_PRIORITY[aggregate]) {
      aggregate = status;
    }
  }
  return aggregate;
};

export const PERSON_WORKSPACE_GATE_NOTICE = __(
  'This route is recognized, but the person workspace stays on the legacy Entries view until enriched roster projection data lands.',
  'alt-context',
);

export const PROJECTION_REFRESHING_NOTICE = __(
  'Roster projection is refreshing. Retry once the refresh completes.',
  'alt-context',
);

export const PROJECTION_STALE_NOTICE = __(
  'Roster projection is stale. Person workspace will resume after the next refresh.',
  'alt-context',
);

export const PROJECTION_FAILED_NOTICE = __(
  'Roster projection failed to refresh. Person workspace is unavailable until the projection recovers.',
  'alt-context',
);

export const PERSON_ROUTE_UNMATCHED_NOTICE = __(
  'No roster entry matches this person route yet. The workspace will appear once a matching projection row is available.',
  'alt-context',
);

/**
 * Shared home for the boarded-up-reassign copy so RosterPage and its
 * ClusterDrawerPanel consumer/tests cannot drift onto separate strings (BR-24).
 */
export const REASSIGN_UNAVAILABLE_REASON = __('Face moves happen in the Review Queue.', 'alt-context');

/**
 * Workbench review-queue deep link for unnamed face groups.
 *
 * Lands on `rq=all.all.0` so the CTA count (top-unlabeled envelope total)
 * matches the landing filter. `cluster=` emission dropped (jobId precedent).
 */
export const workbenchReviewQueueUrl = (): string => {
  // Explicit default band (not serializeQueueState, which omits fully-default).
  // Encoder vocabulary matches parseQueueState / DEFAULT_QUEUE_STATE.
  const base = toWorkbench({ tab: 'scan' });
  const separator = base.includes('?') ? '&' : '?';
  const rq = `${DEFAULT_QUEUE_STATE.kind}.${DEFAULT_QUEUE_STATE.band}.${DEFAULT_QUEUE_STATE.index}`;
  return `${base}${separator}${APP_LINK_PARAMS.rq}=${rq}`;
};
