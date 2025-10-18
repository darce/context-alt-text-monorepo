/**
 * Roster domain normalization utilities.
 *
 * Normalizes roster-related data structures from API responses.
 */

import type { RosterEntry, RosterStats } from "@/admin/types";
import { toFiniteNumber, toStringOrNull } from "./primitives";

/**
 * Normalize roster entry status to valid value.
 */
export const normalizeRosterStatus = (value: unknown): RosterEntry["status"] => {
    const status = typeof value === "string" ? value.toUpperCase() : "";
    if (status === "SYNCED" || status === "CONFLICT") {
        return status;
    }
    return "LOCAL";
};

/**
 * Normalize roster entry from API response.
 *
 * @param entry - Partial roster entry data
 * @returns Normalized roster entry or null if invalid
 */
export const normalizeRosterEntry = (entry: Partial<RosterEntry> | undefined): RosterEntry | null => {
    if (!entry || typeof entry !== "object") {
        return null;
    }

    const label = typeof entry.label === "string" ? entry.label : "";
    const type = typeof entry.type === "string" ? entry.type : "";

    const metadata = entry.metadata && typeof entry.metadata === "object" ? entry.metadata : {};

    const referenceImages = Array.isArray(entry.referenceImages)
        ? entry.referenceImages.filter((item): item is Record<string, unknown> =>
              Boolean(item && typeof item === "object"),
          )
        : [];

    const referenceImageCount = toFiniteNumber(entry.referenceImageCount, 0);

    const resolveAvatarId = (candidate?: unknown): number | null => {
        const value =
            typeof candidate === "number" ? candidate : typeof candidate === "string" ? Number(candidate) : NaN;
        return Number.isFinite(value) && value > 0 ? value : null;
    };

    const directAvatarId = resolveAvatarId(entry.avatarId);
    const metadataAvatarId = (() => {
        if (!metadata) {
            return null;
        }

        const keys = ["avatarAttachmentId", "avatar_attachment_id", "avatarId", "avatar_id"];

        for (const key of keys) {
            if (key in metadata) {
                const resolved = resolveAvatarId(metadata[key]);
                if (resolved !== null) {
                    return resolved;
                }
            }
        }

        return null;
    })();

    const avatarId = directAvatarId ?? metadataAvatarId;
    const mediaCount = toFiniteNumber(entry.mediaCount, entry.media?.length ?? 0);

    return {
        remoteId: toStringOrNull(entry.remoteId),
        label,
        type,
        status: normalizeRosterStatus(entry.status),
        updatedAt: toStringOrNull(entry.updatedAt),
        metadata,
        referenceImages,
        avatarUrl: toStringOrNull(entry.avatarUrl),
        referenceImageCount:
            Number.isFinite(referenceImageCount) && referenceImageCount >= 0
                ? referenceImageCount
                : referenceImages.length,
        avatarId,
        media: entry.media,
        mediaCount,
    };
};

/**
 * Normalize roster stats from API response.
 *
 * @param stats - Partial roster stats data
 * @returns Normalized roster stats with fallback values
 */
export const normalizeRosterStats = (stats: Partial<RosterStats> | undefined): RosterStats => {
    if (!stats || typeof stats !== "object") {
        return {
            total: 0,
            synced: 0,
            local: 0,
            conflicts: 0,
            lastSyncAt: null,
            lastSyncHuman: null,
            metrics: {
                created: 0,
                updated: 0,
                deleted: 0,
                errors: 0,
                conflicts: 0,
            },
        };
    }

    const metrics =
        stats.metrics && typeof stats.metrics === "object" ? (stats.metrics as Record<string, unknown>) : {};

    return {
        total: toFiniteNumber(stats.total, 0),
        synced: toFiniteNumber(stats.synced, 0),
        local: toFiniteNumber(stats.local, 0),
        conflicts: toFiniteNumber(stats.conflicts, 0),
        lastSyncAt: toStringOrNull(stats.lastSyncAt),
        lastSyncHuman: toStringOrNull(stats.lastSyncHuman),
        metrics: {
            created: toFiniteNumber(metrics.created, 0),
            updated: toFiniteNumber(metrics.updated, 0),
            deleted: toFiniteNumber(metrics.deleted, 0),
            errors: toFiniteNumber(metrics.errors, 0),
            conflicts: toFiniteNumber(metrics.conflicts, 0),
        },
    };
};
