import React from 'react';
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';

import { ErrorBoundary } from '../components/ErrorBoundary';
import { RecordedWalkthrough } from '../admin/guidedPrototype/RecordedWalkthrough';
import './index.css';

const assertMountNode: (value: HTMLElement | null) => asserts value is HTMLElement = (value) => {
  if (!(value instanceof HTMLElement)) {
    throw new Error('Public guide mount node #acx-public-guide is missing');
  }
};

const homeUrlFrom = (root: HTMLElement): string => {
  const value = root.getAttribute('data-home-url');
  return value && value.length > 0 ? value : '/';
};

const hideFallback = (root: HTMLElement): void => {
  root.querySelectorAll('.acx-public-guide__fallback').forEach((node) => {
    if (node instanceof HTMLElement) {
      node.hidden = true;
    }
  });
};

export const mountPublicGuide = (
  root: HTMLElement | null = document.getElementById('acx-public-guide'),
): void => {
  assertMountNode(root);
  hideFallback(root);

  let host = root.querySelector<HTMLElement>('.acx-public-guide__app');
  if (host === null) {
    host = document.createElement('div');
    host.className = 'acx-public-guide__app';
    root.appendChild(host);
  }

  const tree = (
    <ErrorBoundary>
      <RecordedWalkthrough scope="public" escapeHref={homeUrlFrom(root)} />
    </ErrorBoundary>
  );
  flushSync(() => {
    createRoot(host).render(tree);
  });
};

const existingRoot = document.getElementById('acx-public-guide');
if (existingRoot) {
  mountPublicGuide(existingRoot);
}
