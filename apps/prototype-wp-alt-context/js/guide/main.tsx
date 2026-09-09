import React from 'react';
import { flushSync } from 'react-dom';
import { createRoot, type Root } from 'react-dom/client';

import { ErrorBoundary } from '../components/ErrorBoundary';
import { RecordedWalkthrough } from '../admin/guidedPrototype/RecordedWalkthrough';
import { PUBLIC_GUIDE_FALLBACK } from '../admin/guidedPrototype/publicGuideCopy';
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

const setFallbackHidden = (root: HTMLElement, hidden: boolean): void => {
  root.querySelectorAll(':scope > .acx-public-guide__fallback').forEach((node) => {
    if (node instanceof HTMLElement) {
      node.hidden = hidden;
    }
  });
};

export interface MountPublicGuideOptions {
  createRoot?: (container: Element | DocumentFragment) => Root;
}

const publicGuideFallback = (
  <p className="acx-public-guide__fallback" role="alert">
    {PUBLIC_GUIDE_FALLBACK}
  </p>
);

export const mountPublicGuide = (
  root: HTMLElement | null = document.getElementById('acx-public-guide'),
  options: MountPublicGuideOptions = {},
): void => {
  assertMountNode(root);
  root.classList.add('acx-public-guide');
  const makeRoot = options.createRoot ?? createRoot;

  let host = root.querySelector<HTMLElement>('.acx-public-guide__app');
  if (host === null) {
    host = document.createElement('div');
    host.className = 'acx-public-guide__app';
    root.appendChild(host);
  }
  const appHost = host;

  const tree = (
    <ErrorBoundary fallback={publicGuideFallback}>
      <RecordedWalkthrough scope="public" escapeHref={homeUrlFrom(root)} />
    </ErrorBoundary>
  );

  let reactRoot: Root | undefined;
  try {
    flushSync(() => {
      reactRoot = makeRoot(appHost);
      reactRoot.render(tree);
    });
    setFallbackHidden(root, true);
  } catch (error) {
    console.error('Public guide failed to mount', error);
    reactRoot?.unmount();
    setFallbackHidden(root, false);
  }
};

const existingRoot = document.getElementById('acx-public-guide');
if (existingRoot) {
  mountPublicGuide(existingRoot);
}
