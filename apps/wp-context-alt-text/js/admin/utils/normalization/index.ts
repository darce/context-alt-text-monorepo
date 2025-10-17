/**
 * Normalization utilities for API data.
 *
 * Provides consistent type coercion and validation across the application.
 *
 * Usage:
 * ```typescript
 * import { toFiniteNumber, normalizeObservationRecord } from '@/admin/utils/normalization';
 *
 * const count = toFiniteNumber(apiResponse.count, 0);
 * const observation = normalizeObservationRecord(apiResponse.observation);
 * ```
 */

// Primitive type coercion
export {
    toFiniteNumber,
    toNumberOrNull,
    toNullableTimestamp,
    toStringOrNull,
    ensureString,
    toBooleanOrNull,
    toUniqueNumericIds,
} from "./primitives";

// Recognition domain
export {
    normalizeCandidates,
    normalizeMatch,
    normalizeRoster,
    normalizeObservationRecord,
    normalizeJobSummary,
    normalizeJobDetails,
} from "./recognition";

export type {
    RecognitionObservationMatch,
    RecognitionObservationRoster,
    RecognitionObservationCandidate,
    RecognitionObservationRecord,
    RecognitionJobSummary,
    RecognitionJobDetails,
} from "./recognition";

// Roster domain
export {
    normalizeRosterStatus,
    normalizeRosterEntry,
    normalizeRosterStats,
} from "./roster";
