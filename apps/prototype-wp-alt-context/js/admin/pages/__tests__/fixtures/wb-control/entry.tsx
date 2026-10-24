import React from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ToastProvider } from '../../../../context/ToastContext';
import { WorkbenchPage } from '../../../WorkbenchPage';
import '../../../../styles/main.scss';

// The production provider tree, selectors, actions and SCSS all run unchanged.
// Browser runner intercepts only transport; it never substitutes components.
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}>
    <ToastProvider>
      <HashRouter>
        <WorkbenchPage />
      </HashRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
