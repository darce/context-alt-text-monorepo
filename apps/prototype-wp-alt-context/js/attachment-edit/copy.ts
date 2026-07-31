/**
 * Single copy source for the post.php attachment-edit surface (UXP-5).
 * Explicitly out of UXP-4 scope until a later copy pass folds it into shared vocabulary.
 */
export const ATTACHMENT_EDIT_COPY = {
  faceDataUnavailable: 'Face data unavailable right now',
  sessionExpired: 'Your session expired — reload the page and sign in again.',
  reloadPage: 'Reload page',
  noFacesDetected: 'No faces detected',
  stillClustering: 'still clustering — reload to refresh',
  loadingFaces: 'Loading face data',
  nameThisPerson: 'Name this person',
} as const;

export function unnamedFaceLabel(faceNumber: number, total: number): string {
  return `Unnamed face ${faceNumber} of ${total}`;
}
