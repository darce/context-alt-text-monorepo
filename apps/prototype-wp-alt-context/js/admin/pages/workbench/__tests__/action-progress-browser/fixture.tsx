// Offline acceptance runs the joined Workbench with its actual provider tree.
// Only HTTP data is replaced by the runner; no UI, hook or host-height aliases.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter } from 'react-router-dom';
import { registerConfig, type ApiConfig } from '../../../../api/config';
import { ToastProvider } from '../../../../context/ToastContext';
import { WorkbenchPage } from '../../../WorkbenchPage';
import '../../../../styles/main.scss';

const configNode = document.getElementById('acx-fixture-config');
if (configNode?.textContent == null) {
  throw new Error('Offline fixture config is missing.');
}
registerConfig(JSON.parse(configNode.textContent) as ApiConfig);
const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
Object.assign(window, { actionProgressHarness: { refetch: () => client.refetchQueries({ type: 'active' }) } });

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}>
    <ToastProvider>
      <HashRouter>
        <WorkbenchPage />
      </HashRouter>
    </ToastProvider>
  </QueryClientProvider>,
);
