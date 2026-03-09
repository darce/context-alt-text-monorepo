import React from 'react';
import { __ } from '@wordpress/i18n';
import { Scan, Users, CheckCircle, ArrowRight } from 'lucide-react';

export const OrientationCard = (): React.JSX.Element => {
  const [isVisible, setIsVisible] = React.useState(() => {
    return localStorage.getItem('acx_orientation_dismissed') !== 'true';
  });

  if (!isVisible) {
    return <></>;
  }

  const handleDismiss = () => {
    localStorage.setItem('acx_orientation_dismissed', 'true');
    setIsVisible(false);
  };

  return (
    <section className="acx-orientation-card" aria-labelledby="acx-orientation-title">
      <div className="acx-orientation-card__header">
        <h2 id="acx-orientation-title">{__('Getting Started with Identity Recognition', 'alt-context')}</h2>
        <button
          type="button"
          className="acx-orientation-card__dismiss"
          onClick={handleDismiss}
          aria-label={__('Dismiss orientation', 'alt-context')}
        >
          {__('Got it, thanks!', 'alt-context')}
        </button>
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
        <a href="#/workbench?tab=scan" className="acx-button acx-button--primary">
          {__('Start your first scan', 'alt-context')}
        </a>
      </div>
    </section>
  );
};
