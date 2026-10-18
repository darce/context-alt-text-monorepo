//// <reference types="vite/client" />

import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { createLogger, withRequestId } from './utils/logger';
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

/**
 * Structural check of the WordPress globals this bundle depends on, taken BEFORE
 * any shim is installed (rg-008: validate what was actually loaded, do not report
 * on the defaults we just supplied). `ensureWordPressGlobalShims` creates `wp` and
 * `wp.hooks`, so reading them afterwards made both warning branches unreachable
 * (FEBT1G-L-14).
 */
const missingWordPressGlobals = (): string[] => {
  const wpGlobal = (window as typeof window & { wp?: { hooks?: unknown } }).wp;
  if (!wpGlobal) {
    return ['wp'];
  }
  return wpGlobal.hooks ? [] : ['wp.hooks'];
};

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

  const missingGlobals = missingWordPressGlobals();

  ensureWordPressGlobalShims();

  if (missingGlobals.length > 0) {
    // Bootstrap is one unit of work; correlate its records explicitly (OBS-03).
    withRequestId(bootstrapLog).warn(`Missing WordPress globals: ${missingGlobals.join(', ')}`, {
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
