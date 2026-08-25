import { getConfig } from '../api/config';

const FALLBACK_MEDIA_EDIT_PATH = '/wp-admin/post.php';
const FALLBACK_ROSTER_PATH = '/wp-admin/admin.php?page=alt-context-roster';
const FALLBACK_MEDIA_LIBRARY_PATH = '/wp-admin/upload.php';

const resolveConfiguredAdminUrl = (configured: string | undefined, fallbackPath: string): string => {
  const target = configured && configured.trim() !== '' ? configured : fallbackPath;
  return new URL(target, window.location.origin).toString();
};

const getMediaEditBase = (): string => {
  try {
    return resolveConfiguredAdminUrl(getConfig().adminUrls.mediaEditBase, FALLBACK_MEDIA_EDIT_PATH);
  } catch {
    return resolveConfiguredAdminUrl(undefined, FALLBACK_MEDIA_EDIT_PATH);
  }
};

export const mediaEditUrl = (mediaId: number): string => {
  const url = new URL(getMediaEditBase());
  url.searchParams.set('post', String(mediaId));
  url.searchParams.set('action', 'edit');
  return url.toString();
};

/** Roster root URL (person-first surface). E21-10 owns further deep-link vocabulary. */
export const rosterUrl = (): string => {
  try {
    return resolveConfiguredAdminUrl(getConfig().adminUrls.roster, FALLBACK_ROSTER_PATH);
  } catch {
    return resolveConfiguredAdminUrl(undefined, FALLBACK_ROSTER_PATH);
  }
};

/** Media library root URL (DUX-W2D6C-RV-07: true-zero empty-state front door). */
export const mediaLibraryUrl = (): string => {
  try {
    return resolveConfiguredAdminUrl(getConfig().adminUrls.mediaLibrary, FALLBACK_MEDIA_LIBRARY_PATH);
  } catch {
    return resolveConfiguredAdminUrl(undefined, FALLBACK_MEDIA_LIBRARY_PATH);
  }
};
