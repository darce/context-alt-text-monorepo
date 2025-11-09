import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';
import { DashboardPage } from './pages/DashboardPage';

const queryClient = new QueryClient();

export const App = (): React.JSX.Element => {
	return (
		<QueryClientProvider client={queryClient}>
			<MemoryRouter initialEntries={['/dashboard']}>
				<Routes>
					<Route path="/dashboard" element={<DashboardPage />} />
					<Route path="*" element={<Navigate to="/dashboard" replace />} />
				</Routes>
			</MemoryRouter>
		</QueryClientProvider>
	);
};
