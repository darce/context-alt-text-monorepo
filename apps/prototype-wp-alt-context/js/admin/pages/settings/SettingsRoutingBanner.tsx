import React from 'react';
import { __ } from '@wordpress/i18n';

import { RecognitionSource, type SettingsResponse } from '../../api/settingsApi';

interface SettingsRoutingBannerProps {
  data: SettingsResponse;
  hasUnsavedRoutingChanges: boolean;
}

export const SettingsRoutingBanner = ({
  data,
  hasUnsavedRoutingChanges,
}: SettingsRoutingBannerProps): React.JSX.Element => {
  const activeModeLabel =
    data.effective_target_mode === RecognitionSource.LOCAL
      ? __('Local development service', 'alt-context')
      : __('Hosted recognition service', 'alt-context');

  return (
    <div
      className="notice notice-info inline acx-settings__routing"
      style={{ marginBottom: '16px' }}
      data-testid="acx-effective-routing"
    >
      <p>
        <strong>{__('Active routing', 'alt-context')}</strong>
        {' — '}
        {activeModeLabel}
        {': '}
        <code>{data.effective_target_url}</code>
      </p>
      {hasUnsavedRoutingChanges ? (
        <p>{__('Save settings before scanning or testing so recognition traffic uses your edits.', 'alt-context')}</p>
      ) : null}
      {data.effective_target_mode === RecognitionSource.LOCAL && data.url ? (
        <p>
          {__(
            'Service URL and API key below are stored for service mode and are not used while Local is selected.',
            'alt-context',
          )}
        </p>
      ) : null}
    </div>
  );
};
