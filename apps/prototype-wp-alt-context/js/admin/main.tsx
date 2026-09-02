//// <reference types="vite/client" />

import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { createLogger } from './utils/logger';
import './styles/main.scss';

const bootstrapLog = createLogger('bootstrap');

type HookFunction = (...args: unknown[]) => void;

interface WpHooksShim {
  doAction: HookFunction;
  addAction: HookFunction;
  removeAction: HookFunction;
  applyFilters: (hookName: string, value: unknown, ...args: unknown[]) => unknown;
  addFilter: HookFunction;
  removeFilter: HookFunction;
  didAction: (hookName: string) => number;
}

interface WpSvgPainterShim {
  init: () => void;
}

interface WpGlobalShim {
  hooks?: WpHooksShim;
  svgPainter?: WpSvgPainterShim;
}

const ensureWordPressGlobalShims = (): void => {
  const win = window as typeof window & { wp?: WpGlobalShim };
  const wpGlobal = (win.wp ??= {});

  wpGlobal.hooks ??= {
    doAction: () => undefined,
    addAction: () => undefined,
    removeAction: () => undefined,
    applyFilters: (_hookName: string, value: unknown) => value,
    addFilter: () => undefined,
    removeFilter: () => undefined,
    didAction: () => 0,
  };

  wpGlobal.svgPainter ??= {
    init: () => undefined,
  };
};

const rootElement = document.getElementById('alt-context-admin-app');
if (rootElement) {
  rootElement.removeAttribute('hidden');

  ensureWordPressGlobalShims();

  const wpGlobal = (window as typeof window & { wp?: { hooks?: unknown } }).wp;
  const missingGlobals: string[] = [];
  if (!wpGlobal) {
    missingGlobals.push('wp');
  } else {
    if (!wpGlobal.hooks) {
      missingGlobals.push('wp.hooks');
    }
  }
  if (missingGlobals.length > 0) {
    bootstrapLog.warn(`Missing WordPress globals: ${missingGlobals.join(', ')}`, {
      missingGlobals,
    });
  }

  const root = createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
