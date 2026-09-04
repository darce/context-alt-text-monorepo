/**
 * Single copy source for the post.php attachment-edit surface (UXP-5).
 *
 * The auth-expiry pair is NOT surface-specific and is deliberately NOT re-declared
 * here: the SPA and post.php answer the same user question ("your session died —
 * reload"), so a wording change to one is always a wording change to the other and
 * they must have one owner (`js/admin/utils/sessionExpiredCopy.ts`). This closes the
 * third verbatim copy of those literals (prior UXP-NET-2 findings #4846 / #4849).
 *
 * The remaining strings answer questions only this surface asks (face data, face
 * counts, clustering state); they have no SPA counterpart and would not change
 * together with anything, so merging them anywhere would be coincidental DRY
 * (REF-10) and they correctly stay local.
 *
 * Do NOT re-wrap the imported values in `__()` — `__(SPA_SESSION_EXPIRED_COPY.x)` is
 * invisible to `wp i18n make-pot` and puts the copy decision back into two modules.
 */
import { SPA_SESSION_EXPIRED_COPY } from '../admin/utils/sessionExpiredCopy';

export const ATTACHMENT_EDIT_COPY = {
  faceDataUnavailable: 'Face data unavailable right now',
  sessionExpired: SPA_SESSION_EXPIRED_COPY.sessionExpired,
  reloadPage: SPA_SESSION_EXPIRED_COPY.reloadPage,
  noFacesDetected: 'No faces detected',
  stillClustering: 'still clustering — reload to refresh',
  loadingFaces: 'Loading face data',
  nameThisPerson: 'Name this person',
} as const;

export const unnamedFaceLabel = (faceNumber: number, total: number): string => {
  return `Unnamed face ${faceNumber} of ${total}`;
};
