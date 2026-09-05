export type RoutePath =
  | '/dashboard'
  | '/workbench'
  | '/roster'
  | '/retention'
  | '/settings'
  | '/description-history'
  | '/guided-prototype';
export const DEFAULT_ROUTE: RoutePath = '/dashboard';

export const extractRouteFromHash = (): RoutePath | null => {
  const hash = window.location.hash.replace('#', '').trim();
  const path = hash.split('?')[0];

  if (path === '/workbench') {
    return '/workbench';
  }

  if (path === '/roster') {
    return '/roster';
  }

  if (path === '/dashboard') {
    return '/dashboard';
  }

  if (path === '/retention') {
    return '/retention';
  }

  if (path === '/settings') {
    return '/settings';
  }

  if (path === '/description-history') {
    return '/description-history';
  }

  if (path === '/guided-prototype') {
    return '/guided-prototype';
  }

  return null;
};

export const ensureHashInitialized = (initialRoute: RoutePath): void => {
  if (typeof window === 'undefined') {
    return;
  }

  const current = extractRouteFromHash();
  if (!current) {
    // Collect all query parameters from window.location.search (except 'page')
    // and append them to the new hash.
    const searchParams = new URLSearchParams(window.location.search);
    searchParams.delete('page'); // WordPress 'page' arg not needed in SPA hash
    const searchString = searchParams.toString();
    const query = searchString ? `?${searchString}` : '';

    window.location.hash = `#${initialRoute}${query}`;
  }
};
