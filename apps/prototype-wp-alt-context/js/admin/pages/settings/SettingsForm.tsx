import React from 'react';
import { __ } from '@wordpress/i18n';

import { RecognitionSource, type SettingsResponse, type TestConnectionResponse } from '../../api/settingsApi';
import {
  HEALTH_STATUS_ICONS,
  HEALTH_STATUS_LABELS,
} from './settingsConstants';
import { healthStatusForService } from './healthStatus';
import { SOURCE_LABELS } from './settingsConstants';

interface SettingsFormProps {
  data: SettingsResponse;
  url: string;
  apiKey: string;
  descriptionBudgetMaxAttempts: string;
  urlReadOnly: boolean;
  keyReadOnly: boolean;
  savePending: boolean;
  testPending: boolean;
  hasUnsavedRoutingChanges: boolean;
  testResult: TestConnectionResponse | null;
  onUrlChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onDescriptionBudgetMaxAttemptsChange: (value: string) => void;
  onSave: (e: React.FormEvent) => void;
  onTest: () => void;
  onFocusServiceUrl?: () => void;
}

export const SettingsForm = ({
  data,
  url,
  apiKey,
  descriptionBudgetMaxAttempts,
  urlReadOnly,
  keyReadOnly,
  savePending,
  testPending,
  hasUnsavedRoutingChanges,
  testResult,
  onUrlChange,
  onApiKeyChange,
  onDescriptionBudgetMaxAttemptsChange,
  onSave,
  onTest,
  onFocusServiceUrl,
}: SettingsFormProps): React.JSX.Element => {
  const serviceConfigured = url.trim() !== '';
  // RECOG-1: local survives only as a dev-only code hatch; when active the
  // effective target resolves to local. Surface it as a read-only diagnostic.
  const devHatchActive = data.recognition_source === RecognitionSource.LOCAL;
  const healthStatus = healthStatusForService(testResult);

  return (
    <form onSubmit={onSave} className="acx-settings__form">
      <h3 className="acx-settings__section-title">{__('Recognition service', 'alt-context')}</h3>

      <div className="acx-target-card acx-target-card--active" data-testid="acx-target-card-service">
        <div className="acx-target-card__header">
          <span className="acx-target-card__title">
            <span>{__('Hosted recognition service', 'alt-context')}</span>
          </span>
          <span className={`acx-target-card__health acx-target-card__health--${healthStatus}`}>
            <span aria-hidden="true" className="acx-target-card__health-icon">
              {HEALTH_STATUS_ICONS[healthStatus]}
            </span>
            {HEALTH_STATUS_LABELS[healthStatus]}
          </span>
        </div>

        {!serviceConfigured ? (
          <div className="acx-target-card__empty">
            <p>{__('No service URL configured yet.', 'alt-context')}</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onFocusServiceUrl?.();
              }}
            >
              {__('Configure service URL', 'alt-context')}
            </button>
          </div>
        ) : (
          <div className="acx-target-card__body">
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
          </div>
        )}

        <div className="acx-target-card__actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={onTest}
            disabled={testPending || hasUnsavedRoutingChanges || !serviceConfigured}
          >
            {testPending ? __('Checking…', 'alt-context') : __('Check health', 'alt-context')}
          </button>
        </div>
      </div>

      <p
        className="description acx-settings__effective-target"
        data-testid="acx-effective-routing"
        role="status"
        aria-live="polite"
      >
        <strong>{__('Effective target', 'alt-context')}</strong>
        {' — '}
        {devHatchActive
          ? __('Local development service (developer hatch)', 'alt-context')
          : __('Hosted recognition service', 'alt-context')}
        {': '}
        <code>{data.effective_target_url || __('not configured', 'alt-context')}</code>
      </p>

      {devHatchActive ? (
        <p className="description">
          {__(
            'Local recognition is enabled via the ACX_RECOGNITION_SOURCE developer constant. Remove it to use the hosted service.',
            'alt-context',
          )}
        </p>
      ) : null}

      {hasUnsavedRoutingChanges ? (
        <p className="description">
          {__('Save settings before scanning or testing so recognition traffic uses your edits.', 'alt-context')}
        </p>
      ) : null}

      <h3 className="acx-settings__section-title">{__('Description budget', 'alt-context')}</h3>
      <label htmlFor="acx-settings-description-budget-max-attempts">
        {__('Maximum description attempts', 'alt-context')}
      </label>
      <input
        id="acx-settings-description-budget-max-attempts"
        type="number"
        className="small-text"
        min="-1"
        step="1"
        value={descriptionBudgetMaxAttempts}
        onChange={(e) => onDescriptionBudgetMaxAttemptsChange(e.target.value)}
      />
      <p className="description">
        {__('-1 means unlimited. Attempts include successful and failed description generations.', 'alt-context')}
      </p>

      <div className="acx-settings__budget-summary" aria-label={__('Description usage', 'alt-context')}>
        <dl>
          <dt>{__('Attempts', 'alt-context')}</dt>
          <dd>{data.description_budget.usage.attempts}</dd>
          <dt>{__('Successes', 'alt-context')}</dt>
          <dd>{data.description_budget.usage.successes}</dd>
          <dt>{__('Failures', 'alt-context')}</dt>
          <dd>{data.description_budget.usage.failures}</dd>
        </dl>
      </div>

      {data.description_budget.recent_errors.length > 0 ? (
        <table className="widefat striped acx-settings__recent-errors">
          <caption>{__('Recent description errors', 'alt-context')}</caption>
          <thead>
            <tr>
              <th scope="col">{__('Media', 'alt-context')}</th>
              <th scope="col">{__('Code', 'alt-context')}</th>
              <th scope="col">{__('Message', 'alt-context')}</th>
            </tr>
          </thead>
          <tbody>
            {data.description_budget.recent_errors.map((error) => (
              <tr key={`${error.media_id}-${error.occurred_at}-${error.error_code ?? ''}`}>
                <td>{error.media_id}</td>
                <td>{error.error_code ?? __('unknown', 'alt-context')}</td>
                <td>{error.error_message ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <p className="submit">
        <button
          type="submit"
          className="button button-primary"
          disabled={savePending || (urlReadOnly && keyReadOnly)}
        >
          {savePending ? __('Saving…', 'alt-context') : __('Save Settings', 'alt-context')}
        </button>
      </p>
    </form>
  );
};
