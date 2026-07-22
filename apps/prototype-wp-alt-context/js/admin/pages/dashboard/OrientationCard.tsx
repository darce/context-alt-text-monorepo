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
            <h3>{__('1. Scan Media', 'alt-context')}</h3>
            <p>
              {__(
                'Analyze your library to detect faces and extract mathematical identities (embeddings).',
                'alt-context',
              )}
            </p>
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
            <h3>{__('2. Cluster Faces', 'alt-context')}</h3>
            <p>
              {__(
                'Automatically group similar faces into "Clusters" to review many identities at once.',
                'alt-context',
              )}
            </p>
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
            <h3>{__('3. Assign Labels', 'alt-context')}</h3>
            <p>
              {__(
                'Name your clusters to automatically populate alt text across your entire media library.',
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
