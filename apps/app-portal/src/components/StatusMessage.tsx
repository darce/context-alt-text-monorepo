import type { ReactNode } from 'react';

export type StatusTone = 'info' | 'ok' | 'error';

function StatusIcon({ tone }: { tone: StatusTone }) {
  const title = tone === 'error' ? 'Error' : tone === 'ok' ? 'Ready' : 'Status';
  return (
    <svg className="acx-status-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      {tone === 'error' ? (
        <path
          fill="currentColor"
          d="M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm.75 3.25a.75.75 0 0 0-1.5 0v4.5a.75.75 0 0 0 1.5 0v-4.5ZM8 12.25a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8Z"
        />
      ) : (
        <circle cx="8" cy="8" r="6" fill="currentColor" />
      )}
      <title>{title}</title>
    </svg>
  );
}

export function StatusMessage({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <p className={`acx-status acx-status-${tone}`} role="status">
      <StatusIcon tone={tone} />
      <span>{children}</span>
    </p>
  );
}
