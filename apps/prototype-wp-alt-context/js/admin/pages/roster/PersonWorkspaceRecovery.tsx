import React from 'react';
import { __ } from '@wordpress/i18n';
import type { useRosterEntries } from '../../hooks/useRosterHooks';

// This bounds client observation, not the shared query or the server's sync work.
const WAIT_LIMIT_MS = 15_000;
type Observation = 'idle' | 'pending' | 'checked' | 'error' | 'timed-out' | 'stopped';

interface PersonWorkspaceRecoveryProps {
  query: Pick<ReturnType<typeof useRosterEntries>, 'isLoading' | 'isError' | 'refetch'>;
  personKey: string | null;
  availability: string;
  unavailable: boolean;
}

export const PersonWorkspaceRecovery = ({
  query,
  personKey,
  availability,
  unavailable,
}: PersonWorkspaceRecoveryProps): React.JSX.Element => {
  const [observation, setObservation] = React.useState<Observation>(query.isLoading ? 'pending' : 'idle');
  const heading = React.useRef<HTMLHeadingElement>(null);
  const refreshButton = React.useRef<HTMLButtonElement>(null);
  const attempt = React.useRef(0);
  const waiting = React.useRef(false);
  const mounted = React.useRef(false);
  const previousPerson = React.useRef<string | null>(null);

  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  React.useEffect(() => {
    if (query.isLoading) {
      setObservation('pending');
    } else {
      setObservation((previous) => (previous === 'pending' ? 'idle' : previous));
    }
  }, [query.isLoading]);

  React.useEffect(() => {
    waiting.current = observation === 'pending';
    if (observation !== 'pending') {
      return;
    }
    const timer = window.setTimeout(() => {
      waiting.current = false;
      setObservation('timed-out');
    }, WAIT_LIMIT_MS);
    return () => window.clearTimeout(timer);
  }, [observation]);

  React.useEffect(() => {
    // Route navigation gets an orientation point. A background read never
    // steals focus from an add/rename/search draft or from the refresh button.
    const navigated = previousPerson.current !== personKey;
    previousPerson.current = personKey;
    if (!navigated || !personKey || !unavailable) {
      return;
    }
    const active = document.activeElement;
    if (
      active instanceof HTMLElement &&
      (active.matches('input, textarea, select, [contenteditable="true"]') || active.closest('.acx-roster-recovery'))
    ) {
      return;
    }
    heading.current?.focus({ preventScroll: true });
  }, [personKey, unavailable]);

  const refresh = async () => {
    if (waiting.current) {
      return;
    }
    waiting.current = true;
    const currentAttempt = ++attempt.current;
    setObservation('pending');
    try {
      // Join an in-flight read after Stop waiting/timeout. Never cancel the
      // shared request, force a sync, or infer freshness from HTTP success.
      const result = await query.refetch({ cancelRefetch: false });
      if (mounted.current && currentAttempt === attempt.current) {
        setObservation(result?.isError ? 'error' : 'checked');
      }
    } catch {
      if (mounted.current && currentAttempt === attempt.current) {
        setObservation('error');
      }
    } finally {
      if (currentAttempt === attempt.current) {
        waiting.current = false;
      }
    }
  };

  const stopWaiting = () => {
    waiting.current = false;
    setObservation('stopped');
    refreshButton.current?.focus();
  };

  const pending = observation === 'pending';
  const failed = !pending && (query.isError || observation === 'error');
  const feedback = pending
    ? __('Checking people… You can keep working or stop waiting.', 'alt-context')
    : failed
      ? __('Could not refresh people. Your selection and drafts are kept. Try refreshing again.', 'alt-context')
      : observation === 'timed-out'
        ? __(
            'Still waiting for people. No new result is confirmed. You can check again; your selection and drafts are kept.',
            'alt-context',
          )
        : observation === 'stopped'
          ? __('Stopped waiting. The read may still finish; your selection and drafts are kept.', 'alt-context')
          : observation === 'checked'
            ? __('People checked.', 'alt-context')
            : '';

  return (
    <div className="acx-roster-recovery" role="group" aria-labelledby="acx-roster-recovery-title">
      <h2 id="acx-roster-recovery-title" ref={heading} tabIndex={-1}>
        {__('People refresh', 'alt-context')}
      </h2>
      <div role="status" aria-atomic="true" id="acx-roster-recovery-status">
        {feedback && <p>{feedback}</p>}
        {!pending && !failed && !query.isLoading && <p>{availability}</p>}
      </div>
      <div className="acx-roster-recovery__actions">
        <button
          type="button"
          className="acx-button acx-button--secondary"
          ref={refreshButton}
          aria-disabled={pending || undefined}
          aria-describedby="acx-roster-recovery-status"
          onClick={() => void refresh()}
        >
          {pending
            ? __('Checking people…', 'alt-context')
            : failed
              ? __('Retry refresh', 'alt-context')
              : __('Refresh people', 'alt-context')}
        </button>
        {pending && (
          <button type="button" className="acx-link-button" onClick={stopWaiting}>
            {__('Stop waiting', 'alt-context')}
          </button>
        )}
      </div>
      <p>
        {__('Refresh checks the latest saved people data. It does not change names or face groups.', 'alt-context')}
      </p>
    </div>
  );
};
