import React from 'react';
import { __ } from '@wordpress/i18n';
import { Scan, Users, CheckCircle, ArrowRight } from 'lucide-react';

import { toWorkbench } from '../../navigation/appLinks';

const ORIENTATION_DISMISSAL = {
  STORAGE_PREFIX: 'acx-orientation-dismissed:',
  DISMISSED: 'true',
} as const;

const getDismissalStorageKey = (): string | null => {
  const userId = window.userSettings?.uid;
  return typeof userId === 'string' || typeof userId === 'number'
    ? `${ORIENTATION_DISMISSAL.STORAGE_PREFIX}${userId}`
    : null;
};

declare global {
  interface Window {
    userSettings?: {
      uid?: string | number;
    };
  }
}

export const OrientationCard = (): React.JSX.Element | null => {
  const storageKey = getDismissalStorageKey();
  const [isDismissed, setIsDismissed] = React.useState(
    () => storageKey !== null && window.localStorage.getItem(storageKey) === ORIENTATION_DISMISSAL.DISMISSED,
  );

  const dismiss = () => {
    if (storageKey !== null) {
      window.localStorage.setItem(storageKey, ORIENTATION_DISMISSAL.DISMISSED);
    }
    setIsDismissed(true);
  };

  if (isDismissed) {
    return null;
  }

  return (
    <section className="acx-orientation-card" aria-labelledby="acx-orientation-title">
      <div className="acx-orientation-card__header">
        <h2 id="acx-orientation-title">{__('Getting Started with Identity Recognition', 'alt-context')}</h2>
        <button type="button" className="acx-orientation-card__dismiss" onClick={dismiss}>
          {__('Dismiss getting started', 'alt-context')}
        </button>
      </div>

      <div className="acx-orientation-card__steps">
        <div className="acx-orientation-card__step">
          <div className="acx-orientation-card__icon-wrapper">
            <Scan size={24} />
          </div>
          <div className="acx-orientation-card__step-content">
            <h3>{__('1. Scan', 'alt-context')}</h3>
            <p>{__('Scan your media library to find faces.', 'alt-context')}</p>
          </div>
        </div>

        <div className="acx-orientation-card__divider">
          <ArrowRight size={20} />
        </div>

        <div className="acx-orientation-card__step">
          <div className="acx-orientation-card__icon-wrapper">
            <Users size={24} />
          </div>
          <div className="acx-orientation-card__step-content">
            <h3>{__('2. Confirm', 'alt-context')}</h3>
            <p>{__('Confirm which faces belong together in face groups.', 'alt-context')}</p>
          </div>
        </div>

        <div className="acx-orientation-card__divider">
          <ArrowRight size={20} />
        </div>

        <div className="acx-orientation-card__step">
          <div className="acx-orientation-card__icon-wrapper">
            <CheckCircle size={24} />
          </div>
          <div className="acx-orientation-card__step-content">
            <h3>{__('3. Review', 'alt-context')}</h3>
            <p>
              {__(
                'Review face groups, name the people in them, and add their names to alt text across your media library.',
                'alt-context',
              )}
            </p>
          </div>
        </div>
      </div>

      <div className="acx-orientation-card__footer">
        <a href={toWorkbench({ tab: 'scan' })} className="acx-button acx-button--primary">
          {__('Start your first scan', 'alt-context')}
        </a>
      </div>
    </section>
  );
};
