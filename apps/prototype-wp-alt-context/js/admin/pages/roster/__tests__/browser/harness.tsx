import React from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { resetConfigCache } from '../../../../api/config';
import { ToastProvider } from '../../../../context/ToastContext';
import { RosterPage } from '../../../RosterPage';
import '../../../../styles/main.scss';

// Actual page, production providers and styles. Only transport/data are fixtures.
window.AltContextAdmin = {
  nonce: 'offline-fixture', ajaxUrl: '/fixture/ajax',
  endpoints: {
    rosterEntries: '/fixture/entries', rosterPersons: '/fixture/persons',
    recognitionClusters: '/fixture/clusters', syncHealth: '/fixture/health',
  },
};
resetConfigCache();
const client = new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={client}><HashRouter><ToastProvider>
    <main className="acx-admin"><RosterPage /></main>
  </ToastProvider></HashRouter></QueryClientProvider>,
);
