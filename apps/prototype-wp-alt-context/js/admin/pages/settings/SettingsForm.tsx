import React from 'react';
import { __ } from '@wordpress/i18n';

import {
  RecognitionSource,
  type RecognitionSourceValue,
  type SettingsResponse,
  type TestConnectionResponse,
} from '../../api/settingsApi';
import { TargetCard, TargetCardGroup } from '../../../components/ui/target-card';
import { healthStatusForTarget } from './healthStatus';
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
  hasUnsavedRoutingChanges: boolean;
  testResult: TestConnectionResponse | null;
  onUrlChange: (value: string) => void;
  onLocalUrlChange: (value: string) => void;
  onRecognitionSourceChange: (value: RecognitionSourceValue) => void;
  onApiKeyChange: (value: string) => void;
  onSave: (e: React.FormEvent) => void;
  onTest: (target: RecognitionSourceValue) => void;
  onFocusServiceUrl?: () => void;
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
  hasUnsavedRoutingChanges,
  testResult,
  onUrlChange,
  onLocalUrlChange,
  onRecognitionSourceChange,
  onApiKeyChange,
  onSave,
  onTest,
  onFocusServiceUrl,
}: SettingsFormProps): React.JSX.Element => {
  const serviceConfigured = url.trim() !== '';
  const localIsEffective = data.effective_target_mode === RecognitionSource.LOCAL;
  const serviceIsEffective = data.effective_target_mode === RecognitionSource.SERVICE;

  return (
    <form onSubmit={onSave} className="acx-settings__form">
      <h3 className="acx-settings__section-title">{__('Recognition target', 'alt-context')}</h3>

      <TargetCardGroup
        value={recognitionSource}
        onValueChange={onRecognitionSourceChange}
        disabled={sourceReadOnly}
      >
        <TargetCard
          id="acx-target-local"
          title={__('Local development', 'alt-context')}
          value={RecognitionSource.LOCAL}
          isEffectiveTarget={localIsEffective}
          deemphasized={recognitionSource !== RecognitionSource.LOCAL && !localIsEffective}
          healthStatus={healthStatusForTarget(RecognitionSource.LOCAL, testResult)}
          configured
          disabled={sourceReadOnly}
          onHealthCheck={() => onTest(RecognitionSource.LOCAL)}
          healthCheckPending={testPending}
          healthCheckDisabled={hasUnsavedRoutingChanges}
        >
          <label htmlFor="acx-settings-local-url">{__('Local service URL', 'alt-context')}</label>
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
            {SOURCE_LABELS[data.local_url_source] ?? data.local_url_source}
            {localUrlReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
          </p>
        </TargetCard>

        <TargetCard
          id="acx-target-service"
          title={__('Hosted service', 'alt-context')}
          value={RecognitionSource.SERVICE}
          isEffectiveTarget={serviceIsEffective}
          deemphasized={recognitionSource !== RecognitionSource.SERVICE && !serviceIsEffective}
          healthStatus={healthStatusForTarget(RecognitionSource.SERVICE, testResult)}
          configured={serviceConfigured}
          disabled={sourceReadOnly}
          emptyStateCta={__('Configure service URL', 'alt-context')}
          onEmptyStateCta={onFocusServiceUrl}
          onHealthCheck={() => onTest(RecognitionSource.SERVICE)}
          healthCheckPending={testPending}
          healthCheckDisabled={hasUnsavedRoutingChanges || !serviceConfigured}
        >
          <label htmlFor="acx-settings-url">{__('Service API URL', 'alt-context')}</label>
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
            {SOURCE_LABELS[data.url_source] ?? data.url_source}
            {urlReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
          </p>
          <label htmlFor="acx-settings-key">{__('API Key', 'alt-context')}</label>
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
        </TargetCard>
      </TargetCardGroup>

      <p className="description acx-settings__effective-target" data-testid="acx-effective-routing">
        <strong>{__('Effective target', 'alt-context')}</strong>
        {' — '}
        {data.effective_target_mode === RecognitionSource.LOCAL
          ? __('Local development service', 'alt-context')
          : __('Hosted recognition service', 'alt-context')}
        {': '}
        <code>{data.effective_target_url}</code>
      </p>

      <p className="description">
        {SOURCE_LABELS[data.recognition_source_source] ?? data.recognition_source_source}
        {sourceReadOnly && <> &mdash; {__('read-only (override active)', 'alt-context')}</>}
      </p>

      {hasUnsavedRoutingChanges ? (
        <p className="description">
          {__('Save settings before scanning or testing so recognition traffic uses your edits.', 'alt-context')}
        </p>
      ) : null}

      <p className="submit">
        <button
          type="submit"
          className="button button-primary"
          disabled={savePending || (sourceReadOnly && urlReadOnly && localUrlReadOnly && keyReadOnly)}
        >
          {savePending ? __('Saving\u2026', 'alt-context') : __('Save Settings', 'alt-context')}
        </button>
      </p>
    </form>
  );
};