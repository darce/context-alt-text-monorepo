//// <reference types="vite/client" />

import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles/main.scss';

const rootElement = document.getElementById('alt-context-admin-app');
if (rootElement) {
  rootElement.removeAttribute('hidden');

  const root = createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
