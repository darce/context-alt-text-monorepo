import { getConfig } from '../api/config';

const FALLBACK_MEDIA_EDIT_PATH = '/wp-admin/post.php';
const FALLBACK_ROSTER_CLUSTERS_PATH = '/wp-admin/admin.php?page=alt-context-roster&tab=clusters';

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

export const rosterClustersUrl = (): string => {
  try {
    return resolveConfiguredAdminUrl(getConfig().adminUrls.rosterClusters, FALLBACK_ROSTER_CLUSTERS_PATH);
  } catch {
    return resolveConfiguredAdminUrl(undefined, FALLBACK_ROSTER_CLUSTERS_PATH);
  }
};
