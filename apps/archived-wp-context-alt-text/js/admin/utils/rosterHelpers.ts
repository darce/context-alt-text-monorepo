/**
 * Roster utility functions for observation and candidate processing
 *
 * These helpers are used throughout the roster components to:
 * - Normalize confidence scores
 * - Rank and select top candidates
 * - Resolve suggested labels and IDs
 * - Format display values
 * - Build URL search parameters
 */

import type { RecognitionObservationRecord, RecognitionObservationCandidate, RosterEntry } from "@/admin/types";

/**
 * Type guard to check if a value is a finite number
 */
export const isFiniteNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/**
 * Normalize confidence value to 0-1 range
 *
 * Handles values that may be:
 * - Already normalized (0-1)
 * - Percentages (>1, will divide by 100)
 * - Invalid (returns null)
 *
 * @param value - Raw confidence value
 * @returns Normalized confidence (0-1) or null if invalid
 *
 * @example
 * ```ts
 * normalizeConfidence(0.95)  // 0.95
 * normalizeConfidence(95)    // 0.95
 * normalizeConfidence(-1)    // null
 * normalizeConfidence("bad") // null
 * ```
 */
export const normalizeConfidence = (value: unknown): number | null => {
    if (!isFiniteNumber(value)) {
        return null;
    }

    const normalized = value > 1 ? value / 100 : value;
    return normalized >= 0 ? normalized : null;
};

/**
 * Get the top-ranked candidate from an observation record
 *
 * Ranking priority:
 * 1. Meets threshold (boolean)
 * 2. Confidence score (higher is better)
 * 3. Similarity score (higher is better)
 *
 * @param record - Observation record with candidates
 * @returns Top candidate or null if none available
 *
 * @example
 * ```ts
 * const top = getTopCandidate(observationRecord);
 * if (top?.meetsThreshold) {
 *   console.log(`Best match: ${top.name} (${top.confidence})`);
 * }
 * ```
 */
export const getTopCandidate = (record: RecognitionObservationRecord): RecognitionObservationCandidate | null => {
    if (!record || !Array.isArray(record.candidates) || record.candidates.length === 0) {
        return null;
    }

    const sorted = [...record.candidates].filter(Boolean).sort((a, b) => {
        // Primary: meets threshold
        const meetsThresholdDelta = Number(b.meetsThreshold) - Number(a.meetsThreshold);
        if (meetsThresholdDelta !== 0) {
            return meetsThresholdDelta;
        }

        // Secondary: confidence score
        const bConfidence = normalizeConfidence(b.confidence) ?? -Infinity;
        const aConfidence = normalizeConfidence(a.confidence) ?? -Infinity;
        if (bConfidence !== aConfidence) {
            return bConfidence - aConfidence;
        }

        // Tertiary: similarity score
        const bSimilarity = isFiniteNumber(b.similarity) ? b.similarity : -Infinity;
        const aSimilarity = isFiniteNumber(a.similarity) ? a.similarity : -Infinity;
        return bSimilarity - aSimilarity;
    });

    return sorted[0] ?? null;
};

/**
 * Resolve the suggested match label for display
 *
 * Prioritization:
 * 1. Roster entry from record.roster.remoteId
 * 2. Roster displayName/name from record
 * 3. Top candidate's roster entry
 * 4. Top candidate's name
 * 5. Top candidate's remoteId
 * 6. Record label
 *
 * @param record - Observation record
 * @param lookup - Map of remoteId to RosterEntry for quick lookups
 * @param top - Top candidate from getTopCandidate
 * @returns Suggested label string or null
 *
 * @example
 * ```ts
 * const label = resolveSuggestedMatchLabel(record, entryMap, topCandidate);
 * // "John Doe (person)" or "Acme Corp (brand)"
 * ```
 */
export const resolveSuggestedMatchLabel = (
    record: RecognitionObservationRecord,
    lookup: Map<string, RosterEntry>,
    top: RecognitionObservationCandidate | null,
): string | null => {
    const labelFromEntry = (remoteId: string | null | undefined): string | null => {
        if (!remoteId) {
            return null;
        }
        const entry = lookup.get(remoteId);
        if (!entry) {
            return null;
        }
        if (entry.label && entry.type) {
            return `${entry.label} (${entry.type})`;
        }

        return entry.label ?? entry.remoteId ?? null;
    };

    const rosterRemote = record?.roster?.remoteId ?? null;
    const rosterLabel = record?.roster?.displayName ?? record?.roster?.name ?? null;

    return (
        labelFromEntry(rosterRemote) ??
        rosterLabel ??
        labelFromEntry(top?.remoteId ?? null) ??
        (top?.name?.trim() ? top.name : null) ??
        top?.remoteId ??
        (record?.label?.trim() ? record.label : null) ??
        null
    );
};

/**
 * Get the confidence value to display for a roster match
 *
 * Prioritization:
 * 1. Roster match similarity (from recognition service)
 * 2. Match confidence
 * 3. Top candidate similarity
 * 4. Top candidate confidence
 *
 * Returns null if there's no match or candidates
 *
 * @param record - Observation record
 * @param top - Top candidate
 * @returns Confidence value (0-1) or null
 *
 * @example
 * ```ts
 * const confidence = getRosterConfidenceValue(record, topCandidate);
 * if (confidence) {
 *   console.log(`Match confidence: ${formatPercentage(confidence)}`);
 * }
 * ```
 */
export const getRosterConfidenceValue = (
    record: RecognitionObservationRecord,
    top: RecognitionObservationCandidate | null,
): number | null => {
    // Only show confidence if there's an actual roster match or valid candidates
    const hasRosterMatch = Boolean(record?.roster?.remoteId) || Boolean(record?.match?.isMatch);
    const hasValidCandidates = Array.isArray(record?.candidates) && record.candidates.length > 0;

    if (!hasRosterMatch && !hasValidCandidates) {
        return null;
    }

    // Prioritize roster similarity (recognition match score) over detection confidence
    const matchSimilarity = normalizeConfidence(record?.match?.similarity);
    if (matchSimilarity !== null && matchSimilarity > 0) {
        return matchSimilarity;
    }

    const candidates = [
        normalizeConfidence(record?.match?.confidence),
        normalizeConfidence(record?.matchConfidence),
        normalizeConfidence(top?.similarity),
        normalizeConfidence(top?.confidence),
    ];

    for (const value of candidates) {
        if (value !== null && value > 0) {
            return value;
        }
    }

    return null;
};

/**
 * Extract detection confidence from observation record
 *
 * Returns the confidence value from face/object detection,
 * as opposed to the recognition/matching confidence.
 *
 * @param record - Observation record
 * @returns Detection confidence value (0-1) or null
 *
 * @example
 * ```ts
 * const detectionConf = getDetectionConfidenceValue(record);
 * if (detectionConf && detectionConf > 0.95) {
 *   console.log("High-quality detection");
 * }
 * ```
 */
export const getDetectionConfidenceValue = (record: RecognitionObservationRecord): number | null => {
    const detection = normalizeConfidence(record?.detectionConfidence);
    if (detection !== null) {
        return detection;
    }

    return normalizeConfidence(record?.confidence);
};

/**
 * Format a decimal value as a localized percentage string
 *
 * Handles different decimal places based on precision:
 * - ≥99.5%: No decimals (100%)
 * - ≥10%: One decimal (95.5%)
 * - <10%: Two decimals (9.87%)
 *
 * @param value - Decimal value (0-1) or percentage (>1)
 * @returns Formatted percentage string or null if invalid
 *
 * @example
 * ```ts
 * formatPercentage(0.957)  // "96%"
 * formatPercentage(0.095)  // "9.5%"
 * formatPercentage(0.0987) // "9.87%"
 * formatPercentage(95.7)   // "96%" (handles percentage input)
 * ```
 */
export const formatPercentage = (value: number | null | undefined): string | null => {
    if (!isFiniteNumber(value)) {
        return null;
    }

    const normalized = value > 1 ? value / 100 : value;

    if (typeof Intl !== "undefined" && Intl.NumberFormat) {
        const formatter = new Intl.NumberFormat(undefined, {
            style: "percent",
            maximumFractionDigits: normalized >= 0.995 ? 0 : normalized >= 0.1 ? 1 : 2,
        });
        return formatter.format(normalized);
    }

    // Fallback for environments without Intl
    const percent = Math.round(normalized * 100);
    return `${percent}%`;
};

/**
 * Resolve the suggested remoteId for an observation
 *
 * Prioritization:
 * 1. Record's roster.remoteId (if exists in lookup)
 * 2. Top candidate's remoteId (if exists in lookup)
 *
 * @param record - Observation record
 * @param lookup - Map of remoteId to RosterEntry
 * @param top - Top candidate
 * @returns Suggested remoteId or null
 *
 * @example
 * ```ts
 * const remoteId = resolveSuggestedRemoteId(record, entryMap, topCandidate);
 * if (remoteId) {
 *   // Pre-select this entry in assignment dialog
 *   setSelectedEntry(remoteId);
 * }
 * ```
 */
export const resolveSuggestedRemoteId = (
    record: RecognitionObservationRecord,
    lookup: Map<string, RosterEntry>,
    top: RecognitionObservationCandidate | null,
): string | null => {
    const fromRoster = record?.roster?.remoteId ?? null;
    if (fromRoster && (lookup.has(fromRoster) || fromRoster.trim() !== "")) {
        return fromRoster;
    }

    const candidateRemote = top?.remoteId ?? null;
    if (candidateRemote && (lookup.has(candidateRemote) || candidateRemote.trim() !== "")) {
        return candidateRemote;
    }

    return null;
};

/**
 * Get the selected remoteId for an observation
 *
 * Returns user's manual selection if available, otherwise returns suggested ID
 *
 * @param record - Observation record
 * @param selection - Map of observationId to user-selected remoteId
 * @param suggested - Suggested remoteId from resolveSuggestedRemoteId
 * @returns Selected remoteId (empty string if none)
 *
 * @example
 * ```ts
 * const selectedId = getSelectedRemoteId(record, userSelections, suggestedId);
 * // Returns user selection if they changed it, otherwise suggested
 * ```
 */
export const getSelectedRemoteId = (
    record: RecognitionObservationRecord,
    selection: Record<string, string>,
    suggested: string | null,
): string => {
    const selected = record?.observationId ? selection[record.observationId] : undefined;
    if (selected && selected.trim() !== "") {
        return selected;
    }

    return suggested ?? "";
};

/**
 * Build URL search parameters for observation prompt deep linking
 *
 * Creates URL parameters that can be used to:
 * - Navigate to observation prompt
 * - Pre-fill form with observation data
 * - Determine create vs edit mode
 *
 * @param record - Observation record with metadata
 * @param attachmentId - WordPress attachment ID
 * @returns URLSearchParams object with observation parameters
 *
 * @example
 * ```ts
 * const params = buildObservationSearchParams(record, 123);
 * navigate(`/roster?${params.toString()}`);
 * // URL: /roster?observationId=obs-42&attachmentId=123&mode=create&label=Person&type=person&source=recognition
 * ```
 */
export const buildObservationSearchParams = (
    record: RecognitionObservationRecord,
    attachmentId: number | null,
): URLSearchParams => {
    const baseSearch = typeof window !== "undefined" ? window.location.search : "";
    const params = new URLSearchParams(baseSearch || undefined);

    if (!record?.observationId) {
        return params;
    }

    params.set("observationId", record.observationId);

    if (attachmentId && Number.isFinite(attachmentId)) {
        params.set("attachmentId", String(attachmentId));
    } else {
        params.delete("attachmentId");
    }

    // Set mode: edit if roster entry exists, create otherwise
    const mode = record?.roster?.remoteId ? "edit" : "create";
    params.set("mode", mode);

    // Set label if available
    if (record?.label?.trim()) {
        params.set("label", record.label.trim());
    } else {
        params.delete("label");
    }

    // Set entity type if available
    if (record?.entityType?.trim()) {
        params.set("type", record.entityType.trim());
    } else {
        params.delete("type");
    }

    // Set remoteId for edit mode
    const remoteId = record?.roster?.remoteId ?? null;
    if (remoteId && remoteId.trim() !== "") {
        params.set("remoteId", remoteId);
    } else {
        params.delete("remoteId");
    }

    // Mark as coming from recognition
    params.set("source", "recognition");

    return params;
};
