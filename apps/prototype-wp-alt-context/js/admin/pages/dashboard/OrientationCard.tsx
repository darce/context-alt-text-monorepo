import React from 'react';
import { __ } from '@wordpress/i18n';
import { Scan, Users, CheckCircle, ArrowRight } from 'lucide-react';

import { toWorkbench } from '../../navigation/appLinks';

interface OrientationCardProps {
  peopleCount: number;
}

export const OrientationCard = ({ peopleCount }: OrientationCardProps): React.JSX.Element | null => {
  if (peopleCount !== 0) {
    return null;
  }

  return (
    <section className="acx-orientation-card" aria-labelledby="acx-orientation-title">
      <div className="acx-orientation-card__header">
        <h2 id="acx-orientation-title">{__('Getting Started with Identity Recognition', 'alt-context')}</h2>
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
