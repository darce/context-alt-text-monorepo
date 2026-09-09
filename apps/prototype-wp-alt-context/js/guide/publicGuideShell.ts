export const PUBLIC_GUIDE_LOAD_TIMEOUT_MS = 8000;

export type PublicGuideShellState = 'loading' | 'ready' | 'error';

export const setPublicGuideShellState = (root: HTMLElement, state: PublicGuideShellState): void => {
  if (state === 'ready') {
    root.setAttribute('data-acx-mounted', '1');
  }

  root.querySelectorAll(':scope > .acx-public-guide__loading').forEach((node) => {
    if (node instanceof HTMLElement) {
      node.hidden = state !== 'loading';
    }
  });
  root.querySelectorAll(':scope > .acx-public-guide__fallback').forEach((node) => {
    if (node instanceof HTMLElement) {
      node.hidden = state !== 'error';
    }
  });
};

const isGuideBundleScript = (target: EventTarget | null): boolean => {
  if (!(target instanceof HTMLScriptElement)) {
    return false;
  }
  const src = target.getAttribute('src') ?? '';
  return target.id === 'acx-public-guide-js' || src.includes('guide');
};

export const attachPublicGuideLoadWatch = (
  root: HTMLElement,
  timeoutMs: number = PUBLIC_GUIDE_LOAD_TIMEOUT_MS,
): (() => void) => {
  const showError = (): void => {
    if (root.getAttribute('data-acx-mounted') === '1') {
      return;
    }
    setPublicGuideShellState(root, 'error');
  };

  const timer = window.setTimeout(showError, timeoutMs);
  const onError = (event: Event): void => {
    if (isGuideBundleScript(event.target)) {
      showError();
    }
  };

  document.addEventListener('error', onError, true);
  return () => {
    window.clearTimeout(timer);
    document.removeEventListener('error', onError, true);
  };
};
