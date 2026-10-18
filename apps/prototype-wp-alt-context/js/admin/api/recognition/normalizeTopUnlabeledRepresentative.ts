/**
 * Wire → internal mapping for RepresentativeResponse / TopUnlabeledRepresentative.
 *
 * Wire (Python alias): is_user_selected, media_id: string | null
 * Internal UI type: is_pinned, media_id: number | null
 */

import type { BoundingBox } from './types/identity';
import type { TopUnlabeledRepresentative } from './types/cluster';

/** Raw payload shape from RepresentativeResponse (top-unlabeled + name suggestions). */
export interface TopUnlabeledRepresentativePayload {
  id: string;
  media_id?: string | null;
  thumb_url?: string | null;
  attachment_url?: string | null;
  media_url?: string | null;
  bbox?: BoundingBox | null;
  is_user_selected?: boolean;
}

const normalizeOptionalUrl = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
};

/**
 * Wire media_id is string|null; parse digit strings to number. Null stays null (never 0).
 */
export const normalizeRepresentativeMediaId = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value !== 'string') {
    return null;
  }
  if (!/^\d+$/.test(value)) {
    return null;
  }
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
};

/**
 * Map RepresentativeResponse wire → internal TopUnlabeledRepresentative.
 * `is_user_selected` → `is_pinned`; strip wire-only keys (explicit object, no spread leak).
 */
export const normalizeTopUnlabeledRepresentative = (
  representative: TopUnlabeledRepresentativePayload,
): TopUnlabeledRepresentative => ({
  id: representative.id,
  media_id: normalizeRepresentativeMediaId(representative.media_id),
  thumb_url: normalizeOptionalUrl(representative.thumb_url ?? null),
  attachment_url: normalizeOptionalUrl(representative.attachment_url ?? null),
  media_url: normalizeOptionalUrl(representative.media_url ?? null),
  bbox: representative.bbox ?? null,
  is_pinned: representative.is_user_selected ?? false,
});
