import React from 'react';
import { __ } from '@wordpress/i18n';

import { RecognitionSource, type RecognitionSourceValue, type SettingsResponse } from '../../api/settingsApi';
import { RadioGroup, RadioGroupItem } from '../../../components/ui/radio-group';
import { SOURCE_LABELS } from './settingsConstants';

interface SettingsFormProps {
  data: SettingsResponse;
  url: string;
  localUrl: string;
  recognitionSource: RecognitionSourceValue;
  apiKey: string;
  sourceReadOnly: boolean;
  urlReadOnly: boolean;
  localUrlReadOnly: boolean;
  keyReadOnly: boolean;
  savePending: boolean;
  testPending: boolean;
  canTestActiveTarget: boolean;
  hasUnsavedRoutingChanges: boolean;
  onUrlChange: (value: string) => void;
  onLocalUrlChange: (value: string) => void;
  onRecognitionSourceChange: (value: RecognitionSourceValue) => void;
  onApiKeyChange: (value: string) => void;
  onSave: (e: React.FormEvent) => void;
  onTest: () => void;
}

export const SettingsForm = ({
  data,
  url,
  localUrl,
  recognitionSource,
  apiKey,
  sourceReadOnly,
  urlReadOnly,
  localUrlReadOnly,
  keyReadOnly,
  savePending,
  testPending,
  canTestActiveTarget,
  hasUnsavedRoutingChanges,
  onUrlChange,
  onLocalUrlChange,
  onRecognitionSourceChange,
  onApiKeyChange,
  onSave,
  onTest,
}: SettingsFormProps): React.JSX.Element => (
  <form onSubmit={onSave} className="acx-settings__form">
    <table className="form-table" role="presentation">
      <tbody>
        <tr>
          <th scope="row">{__('Recognition Source', 'alt-context')}</th>
          <td>
            <fieldset>
              <legend className="screen-reader-text">{__('Recognition Source', 'alt-context')}</legend>
              <RadioGroup
                aria-label={__('Recognition Source', 'alt-context')}
                value={recognitionSource}
                onValueChange={(value) => onRecognitionSourceChange(value as RecognitionSourceValue)}
                disabled={sourceReadOnly}
              >
                <label htmlFor="acx-settings-source-service" style={{ marginRight: '16px' }}>
                  <RadioGroupItem id="acx-settings-source-service" value={RecognitionSource.SERVICE} />{' '}
                  {__('Service', 'alt-context')}
                </label>
                <label htmlFor="acx-settings-source-local">
                  <RadioGroupItem id="acx-settings-source-local" value={RecognitionSource.LOCAL} />{' '}
                  {__('Local', 'alt-context')}
                </label>
              </RadioGroup>
            </fieldset>
            <p className="description">
              {SOURCE_LABELS[data.recognition_source_source] ?? data.recognition_source_source}
              {sourceReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
            </p>
          </td>
        </tr>
        <tr>
          <th scope="row">
            <label htmlFor="acx-settings-local-url">{__('Local service URL', 'alt-context')}</label>
          </th>
          <td>
            <input
              id="acx-settings-local-url"
              type="url"
              className="regular-text"
              value={localUrl}
              onChange={(e) => onLocalUrlChange(e.target.value)}
              readOnly={localUrlReadOnly}
              placeholder="http://localhost:8000"
            />
            <p className="description">
              {__(
                'Used when recognition source is Local. Match the port from make serve (PORT env overrides the default 8000).',
                'alt-context',
              )}
            </p>
            <p className="description">
              {SOURCE_LABELS[data.local_url_source] ?? data.local_url_source}
              {localUrlReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
            </p>
          </td>
        </tr>
        <tr>
          <th scope="row">
            <label htmlFor="acx-settings-url">{__('Service API URL', 'alt-context')}</label>
          </th>
          <td>
            <input
              id="acx-settings-url"
              type="url"
              className="regular-text"
              value={url}
              onChange={(e) => onUrlChange(e.target.value)}
              readOnly={urlReadOnly}
              placeholder="https://api.altcontext.com"
            />
            <p className="description">
              {__('Used when recognition source is Service (for example OCI at api.altcontext.com).', 'alt-context')}
            </p>
            <p className="description">
              {SOURCE_LABELS[data.url_source] ?? data.url_source}
              {urlReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
            </p>
          </td>
        </tr>
        <tr>
          <th scope="row">
            <label htmlFor="acx-settings-key">{__('API Key', 'alt-context')}</label>
          </th>
          <td>
            <input
              id="acx-settings-key"
              type="password"
              className="regular-text"
              value={apiKey}
              onChange={(e) => onApiKeyChange(e.target.value)}
              readOnly={keyReadOnly}
              placeholder={data.api_key_set ? `Current: ${data.api_key_last4}` : __('Enter API key', 'alt-context')}
            />
            <p className="description">
              {SOURCE_LABELS[data.key_source] ?? data.key_source}
              {keyReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
            </p>
          </td>
        </tr>
      </tbody>
    </table>

    <p className="submit">
      <button
        type="submit"
        className="button button-primary"
        disabled={savePending || (sourceReadOnly && urlReadOnly && localUrlReadOnly && keyReadOnly)}
      >
        {savePending ? __('Saving\u2026', 'alt-context') : __('Save Settings', 'alt-context')}
      </button>
      <button
        type="button"
        className="button"
        onClick={onTest}
        disabled={testPending || !canTestActiveTarget || hasUnsavedRoutingChanges}
        style={{ marginLeft: '8px' }}
      >
        {testPending ? __('Testing\u2026', 'alt-context') : __('Test active target', 'alt-context')}
      </button>
    </p>
  </form>
);
