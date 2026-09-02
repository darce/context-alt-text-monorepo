import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import {
  RecognitionSource,
  UrlRejectionReason,
  type SettingsResponse,
  type TestConnectionResponse,
  type UrlRejectionReasonValue,
} from '../../api/settingsApi';
import {
  deriveServiceUrlCardState,
  HEALTH_STATUS_ICONS,
  HEALTH_STATUS_LABELS,
  ServiceUrlCardState,
  SOURCE_LABELS,
  TENANT_PAIRING_ICONS,
  TENANT_PAIRING_LABELS,
  TenantPairing,
} from './settingsConstants';
import { healthStatusForService } from './healthStatus';

const URL_REJECTION_REASON_LABELS: Record<UrlRejectionReasonValue, string> = {
  [UrlRejectionReason.REJECTED_SCHEME]: __(
    'scheme must be HTTPS (HTTP is allowed only for loopback development hosts)',
    'alt-context',
  ),
  [UrlRejectionReason.NON_LOOPBACK_HTTP]: __(
    'HTTP is only allowed for loopback development hosts (localhost, 127.0.0.1, ::1)',
    'alt-context',
  ),
  [UrlRejectionReason.INVALID_URL]: __('the configured value is not a valid URL', 'alt-context'),
};

const urlRejectionStatusText = (data: SettingsResponse): string => {
  const reason = data.url_rejection_reason;
  const reasonLabel =
    reason !== null
      ? (URL_REJECTION_REASON_LABELS[reason] ?? reason)
      : __('unknown reason', 'alt-context');
  const sourceLabel =
    data.url_rejection_source !== null
      ? (SOURCE_LABELS[data.url_rejection_source] ?? data.url_rejection_source)
      : __('unknown source', 'alt-context');
  const rejectedValue = data.url_rejection_value ?? '';

  if (rejectedValue !== '') {
    return sprintf(
      /* translators: %s placeholders: rejected URL, source label, rejection reason */
      __('Rejected %s (%s): %s', 'alt-context'),
      rejectedValue,
      sourceLabel,
      reasonLabel,
    );
  }

  return sprintf(
    /* translators: %s placeholders: source label, rejection reason */
    __('Rejected (%s): %s', 'alt-context'),
    sourceLabel,
    reasonLabel,
  );
};

interface SettingsFormProps {
  data: SettingsResponse;
  url: string;
  apiKey: string;
  descriptionBudgetMaxAttempts: string;
  recognitionEnabled: boolean;
  urlReadOnly: boolean;
  keyReadOnly: boolean;
  savePending: boolean;
  testPending: boolean;
  hasUnsavedRoutingChanges: boolean;
  testResult: TestConnectionResponse | null;
  onUrlChange: (value: string) => void;
  onApiKeyChange: (value: string) => void;
  onDescriptionBudgetMaxAttemptsChange: (value: string) => void;
  onRecognitionEnabledChange: (value: boolean) => void;
  onSave: (e: React.FormEvent) => void;
  onTest: () => void;
  onFocusServiceUrl?: () => void;
}

export const SettingsForm = ({
  data,
  url,
  apiKey,
  descriptionBudgetMaxAttempts,
  recognitionEnabled,
  urlReadOnly,
  keyReadOnly,
  savePending,
  testPending,
  hasUnsavedRoutingChanges,
  testResult,
  onUrlChange,
  onApiKeyChange,
  onDescriptionBudgetMaxAttemptsChange,
  onRecognitionEnabledChange,
  onSave,
  onTest,
  onFocusServiceUrl,
}: SettingsFormProps): React.JSX.Element => {
  // R19-BR-04: one derived state drives empty CTA + source chip; do not re-check
  // url emptiness (resolver blanks url on rejection for security).
  const cardState = deriveServiceUrlCardState(data);
  // R19-BR-05: test_connection probes effective_target_url, not the blanked url.
  const hasProbeTarget = data.effective_target_url.trim() !== '';
  // RECOG-1: local survives only as a dev-only code hatch; when active the
  // effective target resolves to local. Surface it as a read-only diagnostic.
  const devHatchActive = data.recognition_source === RecognitionSource.LOCAL;
  const healthStatus = healthStatusForService(testResult);
  const pairingStatus = data.tenant_paired ? TenantPairing.PAIRED : TenantPairing.UNPAIRED;
  // Rejected installs report url_source=default; surface the tier that held the
  // rejected value so the chip does not claim "Not configured".
  const urlSourceLabel =
    cardState === ServiceUrlCardState.REJECTED && data.url_rejection_source !== null
      ? (SOURCE_LABELS[data.url_rejection_source] ?? data.url_rejection_source)
      : (SOURCE_LABELS[data.url_source] ?? data.url_source);

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

        <div className="acx-target-card__body">
          {cardState === ServiceUrlCardState.UNCONFIGURED ? (
            <div className="acx-target-card__empty">
              <p>{__('No service URL configured yet. Enter the hosted recognition service URL to begin.', 'alt-context')}</p>
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
          ) : null}
          {cardState === ServiceUrlCardState.REJECTED ? (
            <div className="acx-target-card__empty" data-testid="acx-url-rejection-notice">
              {/*
                R16-BR-09: full rejection sentence lives only in the always-mounted
                effective-target live region below (announced once). Card cue is a
                short next-step prompt so sighted operators still know what to do.
              */}
              <p>
                {__(
                  'The configured service URL was rejected. Enter a valid HTTPS URL below to restore recognition routing.',
                  'alt-context',
                )}
              </p>
            </div>
          ) : null}
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
          <p className="description" data-testid="acx-url-source">
            {urlSourceLabel}
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

        <div className="acx-target-card__actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={onTest}
            disabled={testPending || hasUnsavedRoutingChanges || !hasProbeTarget}
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
        {hasProbeTarget ? (
          <code>{data.effective_target_url}</code>
        ) : data.url_rejection_reason === null ? (
          <code>{__('not configured', 'alt-context')}</code>
        ) : null}
        {data.url_rejection_reason !== null ? (
          <>
            {hasProbeTarget ? ' — ' : null}
            <span
              className="acx-settings__url-rejection"
              data-testid="acx-url-rejection"
              style={{ color: 'var(--acx-color-danger)' }}
            >
              {urlRejectionStatusText(data)}
            </span>
          </>
        ) : null}
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

      <h3 className="acx-settings__section-title">{__('Tenant identity', 'alt-context')}</h3>
      <div className="acx-settings__tenant" data-testid="acx-tenant-identity">
        <p className="acx-settings__tenant-row">
          <span className="acx-settings__tenant-label">{__('Tenant ID', 'alt-context')}</span>
          {data.tenant_id ? (
            <code className="acx-settings__tenant-id" data-testid="acx-tenant-id">
              {data.tenant_id}
            </code>
          ) : (
            <span className="acx-settings__tenant-empty">{__('Not assigned yet', 'alt-context')}</span>
          )}
        </p>
        <p className="description">{SOURCE_LABELS[data.tenant_id_source] ?? data.tenant_id_source}</p>
        <p
          className={`acx-settings__tenant-status acx-settings__tenant-status--${pairingStatus}`}
          data-testid="acx-tenant-pairing-status"
          role="status"
          aria-live="polite"
        >
          <span aria-hidden="true" className="acx-settings__tenant-status-icon">
            {TENANT_PAIRING_ICONS[pairingStatus]}
          </span>
          {TENANT_PAIRING_LABELS[pairingStatus]}
        </p>
      </div>

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

      <h3 className="acx-settings__section-title">{__('People & recognition', 'alt-context')}</h3>
      <div className="acx-settings__recognition">
        <label
          htmlFor="acx-settings-recognition-enabled"
          className="acx-settings__recognition-option"
        >
          <input
            id="acx-settings-recognition-enabled"
            type="checkbox"
            checked={recognitionEnabled}
            onChange={(e) => onRecognitionEnabledChange(e.target.checked)}
          />
          {__('Identify people in photos', 'alt-context')}
        </label>
        <p className="description">
          {__(
            'Uses facial recognition to name people in descriptions. When off, Describe writes alt text without identities. Applies to every run.',
            'alt-context',
          )}
        </p>
      </div>

      <p className="submit">
        <button
          type="submit"
          className="button button-primary"
          disabled={savePending}
        >
          {savePending ? __('Saving…', 'alt-context') : __('Save Settings', 'alt-context')}
        </button>
      </p>
    </form>
  );
};
