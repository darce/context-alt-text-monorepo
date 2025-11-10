import React from 'react';
import { __ } from '@wordpress/i18n';

/**
 * Dashboard landing page for the Alt Context admin SPA.
 *
 * Displays a hero section with contextual copy so the React bundle
 * immediately communicates that it has mounted correctly inside wp-admin.
 */
export const DashboardPage = (): React.JSX.Element => {
  return (
    <section className="acx-dashboard__shell" aria-labelledby="acx-dashboard-title">
      <header className="acx-dashboard__hero">
        <p className="acx-dashboard__eyebrow">{__('Alt Context', 'alt-context')}</p>
        <h1 id="acx-dashboard-title" className="acx-dashboard__title">
          {__('Alt Context Dashboard', 'alt-context')}
        </h1>
        <p className="acx-dashboard__subtitle">
          {__(
            'Welcome to the new single-page admin experience. This screen will soon display coverage insights, recent activity, and shortcuts into the workbench.',
            'alt-context',
          )}
        </p>
      </header>

      <div className="acx-dashboard__panels">
        <section className="acx-dashboard__panel">
          <h2>{__('Getting Started', 'alt-context')}</h2>
          <p>
            {__(
              'The React application is now running inside wp-admin. Use this panel to verify the SPA mount point and begin wiring live data.',
              'alt-context',
            )}
          </p>
        </section>

        <section className="acx-dashboard__panel">
          <h2>{__('Next Steps', 'alt-context')}</h2>
          <ul>
            <li>{__('Connect the recognition service endpoint.', 'alt-context')}</li>
            <li>{__('Surface coverage metrics from wp-admin APIs.', 'alt-context')}</li>
            <li>{__('Link to the workbench, roster, and account settings routes.', 'alt-context')}</li>
          </ul>
        </section>
      </div>
    </section>
  );
};
