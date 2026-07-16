import React, { useMemo } from 'react';
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { DashboardPage } from './pages/DashboardPage';
import { RetentionPage } from './pages/RetentionPage';
import { WorkbenchPage } from './pages/WorkbenchPage';
import { RosterPage } from './pages/RosterPage';
import { SettingsPage } from './pages/SettingsPage';
import { DescriptionHistoryPage } from './pages/DescriptionHistoryPage';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { ToastProvider } from './context/ToastContext';
import { DegradedModeBanner } from './pages/workbench/DegradedModeBanner';
import { extractRouteFromHash, ensureHashInitialized, type RoutePath, DEFAULT_ROUTE } from './utils/routeHelpers';
import { HTTPError } from './utils/http';
import { noteRateLimited } from './utils/rateLimitCooldown';

/** Max retries after the first failure (API-08: ~3 total attempts). */
export const QUERY_MAX_RETRIES = 2;

const isAbortLike = (error: unknown): boolean => {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return true;
  }
  if (error instanceof Error && error.name === 'AbortError') {
    return true;
  }
  return false;
};

/** Start shared poller cooldown on any 429 (RES-15 client-side breaker). */
const note429IfPresent = (error: unknown): void => {
  if (error instanceof HTTPError && error.status === 429) {
    noteRateLimited(error.retryAfterSeconds);
  }
};

/**
 * Status-aware query retry (RES-06/API-08).
 * Never retries unmodified 4xx except 429; 429 and 5xx/network are bounded.
 * AbortError is timeout classification — never HTTP-retried.
 */
export const shouldRetryQuery = (failureCount: number, error: unknown): boolean => {
  if (failureCount >= QUERY_MAX_RETRIES) {
    return false;
  }
  if (isAbortLike(error)) {
    return false;
  }
  if (error instanceof HTTPError) {
    if (error.status === 429) {
      noteRateLimited(error.retryAfterSeconds);
      return true;
    }
    if (error.status >= 400 && error.status < 500) {
      return false;
    }
    return true;
  }
  // Network / non-HTTP errors: keep bounded retry.
  return true;
};

/**
 * Bounded exponential backoff (RES-06), with 429 + Retry-After honoring the server.
 * Also arms the shared poller cooldown so concurrent pollers pause (RES-15).
 */
export const getQueryRetryDelay = (attemptIndex: number, error: unknown): number => {
  if (error instanceof HTTPError && error.status === 429) {
    noteRateLimited(error.retryAfterSeconds);
    if (error.retryAfterSeconds != null) {
      return error.retryAfterSeconds * 1000;
    }
  }
  return Math.min(1000 * 2 ** attemptIndex, 30000);
};

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      note429IfPresent(error);
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      note429IfPresent(error);
    },
  }),
  defaultOptions: {
    queries: {
      retry: shouldRetryQuery,
      retryDelay: getQueryRetryDelay,
      refetchOnWindowFocus: false,
    },
  },
});

export const App = (): React.JSX.Element => {
  const initialRoute = useMemo(() => determineInitialRoute(), []);
  ensureHashInitialized(initialRoute);

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <HashRouter>
          <DegradedModeBanner />
          <Routes>
            <Route
              path="/dashboard"
              element={
                <ErrorBoundary>
                  <DashboardPage />
                </ErrorBoundary>
              }
            />
            <Route
              path="/workbench"
              element={
                <ErrorBoundary>
                  <WorkbenchPage />
                </ErrorBoundary>
              }
            />
            <Route
              path="/roster"
              element={
                <ErrorBoundary>
                  <RosterPage />
                </ErrorBoundary>
              }
            />
            <Route
              path="/retention"
              element={
                <ErrorBoundary>
                  <RetentionPage />
                </ErrorBoundary>
              }
            />
            <Route
              path="/settings"
              element={
                <ErrorBoundary>
                  <SettingsPage />
                </ErrorBoundary>
              }
            />
            <Route
              path="/description-history"
              element={
                <ErrorBoundary>
                  <DescriptionHistoryPage />
                </ErrorBoundary>
              }
            />
            <Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
          </Routes>
        </HashRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
};

export const determineInitialRoute = (): RoutePath => {
  const hashRoute = extractRouteFromHash();
  if (hashRoute) {
    return hashRoute;
  }

  const params = new URLSearchParams(window.location.search);
  const page = params.get('page');

  if (page === 'alt-context-workbench') {
    return '/workbench';
  }

  if (page === 'alt-context-roster') {
    return '/roster';
  }

  if (page === 'alt-context-retention') {
    return '/retention';
  }

  if (page === 'alt-context-settings') {
    return '/settings';
  }

  if (page === 'alt-context-description-history') {
    return '/description-history';
  }

  return DEFAULT_ROUTE;
};
