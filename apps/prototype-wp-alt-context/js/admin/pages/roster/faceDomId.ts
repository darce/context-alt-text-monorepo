const DOM_ID_SAFE = /^[A-Za-z0-9_-]+$/;

export const sanitizeDomIdToken = (raw: string): string => {
  if (typeof raw === 'string' && raw.length > 0 && DOM_ID_SAFE.test(raw)) {
    return raw;
  }
  const source = typeof raw === 'string' ? raw : String(raw ?? '');
  let hash = 0x811c9dc5;
  for (let i = 0; i < source.length; i += 1) {
    hash ^= source.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `h${(hash >>> 0).toString(36)}`;
};

export const rosterFaceDomId = (faceId: string): string => `acx-roster-face-${sanitizeDomIdToken(faceId)}`;
