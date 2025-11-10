import React, { useMemo } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { DashboardPage } from './pages/DashboardPage';
import { WorkbenchPage } from './pages/WorkbenchPage';
import { RosterPage } from './pages/RosterPage';

const queryClient = new QueryClient();
const DEFAULT_ROUTE: RoutePath = '/dashboard';

export const App = (): React.JSX.Element => {
	const initialRoute = useMemo(() => determineInitialRoute(), []);
	ensureHashInitialized(initialRoute);

	return (
		<QueryClientProvider client={queryClient}>
			<HashRouter>
				<Routes>
					<Route path="/dashboard" element={<DashboardPage />} />
					<Route path="/workbench" element={<WorkbenchPage />} />
					<Route path="/roster" element={<RosterPage />} />
					<Route path="*" element={<Navigate to={DEFAULT_ROUTE} replace />} />
				</Routes>
			</HashRouter>
		</QueryClientProvider>
	);
};

type RoutePath = '/dashboard' | '/workbench' | '/roster';

function determineInitialRoute(): RoutePath {
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
}

function extractRouteFromHash(): RoutePath | null {
	const hash = window.location.hash.replace('#', '').trim();
	if (hash === '/workbench') {
		return '/workbench';
	}

	if (hash === '/roster') {
		return '/roster';
	}

	if (hash === '/dashboard') {
		return '/dashboard';
	}

	return null;
}

function ensureHashInitialized(initialRoute: RoutePath): void {
	if (typeof window === 'undefined') {
		return;
	}

	const current = extractRouteFromHash();
	if (!current) {
		window.location.hash = `#${initialRoute}`;
	}
}
