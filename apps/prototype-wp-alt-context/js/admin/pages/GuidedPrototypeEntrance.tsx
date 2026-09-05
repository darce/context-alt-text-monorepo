import React from 'react';

export type GuidedEntranceState = 'active' | 'expired' | 'unauthorized';

export interface GuidedPrototypeEntranceProps {
  sessionState?: GuidedEntranceState;
  onBegin: () => void;
  onReauthenticate?: () => void;
}

export const GuidedPrototypeEntrance = ({
  sessionState = 'active',
  onBegin,
  onReauthenticate = onBegin,
}: GuidedPrototypeEntranceProps): React.JSX.Element => {
  const isActive = sessionState === 'active';

  return (
    <section className="acx-guided-entrance" aria-labelledby="acx-guided-entrance-title">
      <div className="acx-guided-entrance__brand" aria-label="Alt Context">
        <span className="acx-guided-entrance__mark" aria-hidden="true">
          AC
        </span>
        <span>Alt Context</span>
      </div>
      <p className="acx-guided-entrance__eyebrow">WordPress plugin practice space</p>
      <h1 id="acx-guided-entrance-title">Guided description review</h1>
      <p className="acx-guided-entrance__intro">
        Follow one saved example from image context to an edited description. You decide what gets applied to the
        practice copy.
      </p>

      {isActive ? (
        <div className="acx-guided-entrance__session" role="status" aria-live="polite">
          <strong>Authenticated WordPress session</strong>
          <span>Only you can confirm identity, edit the draft, or apply it.</span>
        </div>
      ) : (
        <div className="acx-guided-entrance__session acx-guided-entrance__session--warning" role="alert">
          <strong>
            {sessionState === 'expired'
              ? 'Your WordPress session has expired.'
              : 'This practice is for signed-in editors.'}
          </strong>
          <span>
            {sessionState === 'expired'
              ? 'Sign in again to continue safely.'
              : 'Return to the authenticated plugin to continue.'}
          </span>
        </div>
      )}

      {isActive ? (
        <button type="button" className="acx-button acx-button--primary" onClick={onBegin}>
          Start the guided review
        </button>
      ) : (
        <button type="button" className="acx-button acx-button--secondary" onClick={onReauthenticate}>
          Return to WordPress
        </button>
      )}

      <p className="acx-guided-entrance__boundary">
        Practice data is illustrative. Guest invitations and live generation are planned for a later phase.
      </p>
    </section>
  );
};

GuidedPrototypeEntrance.displayName = 'GuidedPrototypeEntrance';
