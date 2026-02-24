import React, { useMemo } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { DashboardPage } from './pages/DashboardPage';
import { WorkbenchPage } from './pages/WorkbenchPage';
import { RosterPage } from './pages/RosterPage';
import { ErrorBoundary } from '../components/ErrorBoundary';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      refetchOnWindowFocus: false,
    },
  },
});
const DEFAULT_ROUTE: RoutePath = '/dashboard';

export const App = (): React.JSX.Element => {
  const initialRoute = useMemo(() => determineInitialRoute(), []);
  ensureHashInitialized(initialRoute);

  return (
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <Routes>
          <Route path="/dashboard" element={<ErrorBoundary><DashboardPage /></ErrorBoundary>} />
          <Route path="/workbench" element={<ErrorBoundary><WorkbenchPage /></ErrorBoundary>} />
          <Route path="/roster" element={<ErrorBoundary><RosterPage /></ErrorBoundary>} />
          <Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
        </Routes>
      </HashRouter>
    </QueryClientProvider>
  );
};

type RoutePath = '/dashboard' | '/workbench' | '/roster';

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

const extractRouteFromHash = (): RoutePath | null => {
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

  return null;
};

const ensureHashInitialized = (initialRoute: RoutePath): void => {
  if (typeof window === 'undefined') {
    return;
  }

  const current = extractRouteFromHash();
  if (!current) {
    window.location.hash = `#${initialRoute}`;
  }
};
