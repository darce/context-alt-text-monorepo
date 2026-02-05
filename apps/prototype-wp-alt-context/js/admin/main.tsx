//// <reference types="vite/client" />

import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles/main.scss';

const rootElement = document.getElementById('alt-context-admin-app');
if (rootElement) {
  rootElement.removeAttribute('hidden');

  const wpGlobal = (window as typeof window & { wp?: { hooks?: unknown; i18n?: unknown } }).wp;
  const missingGlobals: string[] = [];
  if (!wpGlobal) {
    missingGlobals.push('wp');
  } else {
    if (!wpGlobal.hooks) {
      missingGlobals.push('wp.hooks');
    }
    if (!wpGlobal.i18n) {
      missingGlobals.push('wp.i18n');
    }
  }
  if (missingGlobals.length > 0) {
    console.warn(`[alt-context] Missing WordPress globals: ${missingGlobals.join(', ')}`);
  }

  const root = createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
