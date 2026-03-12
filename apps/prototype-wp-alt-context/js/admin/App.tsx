import React, { useMemo } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { DashboardPage } from './pages/DashboardPage';
import { RetentionPage } from './pages/RetentionPage';
import { WorkbenchPage } from './pages/WorkbenchPage';
import { RosterPage } from './pages/RosterPage';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { ToastProvider } from './context/ToastContext';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      refetchOnWindowFocus: false,
    },
  },
});
import { extractRouteFromHash, ensureHashInitialized, type RoutePath, DEFAULT_ROUTE } from './utils/routeHelpers';

export const App = (): React.JSX.Element => {
  const initialRoute = useMemo(() => determineInitialRoute(), []);
  ensureHashInitialized(initialRoute);

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <HashRouter>
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
            <Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
          </Routes>
        </HashRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
};

const determineInitialRoute = (): RoutePath => {
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

  return DEFAULT_ROUTE;
};
