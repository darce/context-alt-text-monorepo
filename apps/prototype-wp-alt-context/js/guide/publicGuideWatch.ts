import {
  attachPublicGuideLoadWatch,
  PUBLIC_GUIDE_LOAD_TIMEOUT_MS,
} from './publicGuideShell';

export const bootPublicGuideWatch = (
  root: HTMLElement | null = document.getElementById('acx-public-guide'),
): (() => void) | null => {
  if (!(root instanceof HTMLElement)) {
    return null;
  }

  const parsed = Number.parseInt(root.getAttribute('data-acx-load-timeout') ?? '', 10);
  const timeoutMs = Number.isFinite(parsed) && parsed >= 1 ? parsed : PUBLIC_GUIDE_LOAD_TIMEOUT_MS;
  return attachPublicGuideLoadWatch(root, timeoutMs);
};

bootPublicGuideWatch();
