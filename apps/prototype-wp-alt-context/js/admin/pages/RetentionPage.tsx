import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { AlertTriangle } from 'lucide-react';

import { RadioGroup, RadioGroupItem } from '../../components/ui/radio-group';
import type { RetentionMode } from '../api/recognition';
import { useRetentionPageState, RETENTION_OPTIONS } from './retention/useRetentionPageState';
import { ExportDialog, PurgeDialog, ImportDialog } from './retention/RetentionDialogs';
import { formatTimestamp } from './retention/AuditTimeline';
import { toUserMessage } from '../utils/appError';
import { toDescriptionHistory } from '../navigation/appLinks';

const EXPORT_JOB_STATUS = {
  completed: 'completed',
  failed: 'failed',
} as const;

const UNAVAILABLE_REASON = {
  NOT_CONFIGURED: 'not_configured',
  API_KEY_MISSING: 'api_key_missing',
  CIRCUIT_OPEN: 'circuit_open',
  UPSTREAM_5XX: 'upstream_5xx',
  UPSTREAM_4XX: 'upstream_4xx',
  TIMEOUT: 'timeout',
  CONTRACT_MISMATCH: 'contract_mismatch',
} as const;

const UNAVAILABLE_SERVICE = {
  RECOGNITION: 'recognition',
  SCENE: 'scene',
} as const;

interface ServiceUnavailable {
  reason: string;
  service: string;
  http_status: number | null;
  retry_after_seconds: number | null;
  checked_at: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const parseUnavailable = (value: unknown): ServiceUnavailable | null => {
  if (!isRecord(value)) {
    return null;
  }
  if (typeof value.reason !== 'string' || value.reason.trim() === '') {
    return null;
  }
  if (typeof value.service !== 'string' || value.service.trim() === '') {
    return null;
  }
  if (value.http_status !== null && value.http_status !== undefined) {
    if (typeof value.http_status !== 'number' || !Number.isFinite(value.http_status)) {
      return null;
    }
  }
  if (value.retry_after_seconds !== null && value.retry_after_seconds !== undefined) {
    if (typeof value.retry_after_seconds !== 'number' || !Number.isFinite(value.retry_after_seconds)) {
      return null;
    }
  }
  if (typeof value.checked_at !== 'string' || value.checked_at.trim() === '') {
    return null;
  }
  return {
    reason: value.reason,
    service: value.service,
    http_status: typeof value.http_status === 'number' ? value.http_status : null,
    retry_after_seconds: typeof value.retry_after_seconds === 'number' ? value.retry_after_seconds : null,
    checked_at: value.checked_at,
  };
};

const readUnavailable = (payload: unknown): ServiceUnavailable | null => {
  if (!isRecord(payload)) {
    return null;
  }
  return parseUnavailable(payload.unavailable);
};

const unavailableServiceLabel = (service: string): string => {
  switch (service) {
    case UNAVAILABLE_SERVICE.RECOGNITION:
      return __('Recognition service', 'alt-context');
    case UNAVAILABLE_SERVICE.SCENE:
      return __('Description service', 'alt-context');
    default:
      return __('Service', 'alt-context');
  }
};

const unavailableReasonCopy = (reason: string): { why: string; fix: string } => {
  switch (reason) {
    case UNAVAILABLE_REASON.NOT_CONFIGURED:
      return {
        why: __('it is not configured', 'alt-context'),
        fix: __('Set the API URL in Settings.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.API_KEY_MISSING:
      return {
        why: __('the API key is missing', 'alt-context'),
        fix: __('Add the API key in Settings.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.CIRCUIT_OPEN:
      return {
        why: __('the circuit breaker is open', 'alt-context'),
        fix: __('Wait for the cooldown, then Retry.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.UPSTREAM_5XX:
      return {
        why: __('it returned a server error', 'alt-context'),
        fix: __('Retry in a moment. If it continues, check the service logs.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.UPSTREAM_4XX:
      return {
        why: __('it rejected the request', 'alt-context'),
        fix: __('Check the API URL and key in Settings.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.TIMEOUT:
      return {
        why: __('it did not respond in time', 'alt-context'),
        fix: __('Retry. If it continues, check that the host is reachable.', 'alt-context'),
      };
    case UNAVAILABLE_REASON.CONTRACT_MISMATCH:
      return {
        why: __('it returned a response this plugin does not recognize', 'alt-context'),
        fix: __('Confirm the plugin and service are on compatible versions.', 'alt-context'),
      };
    default:
      return {
        why: sprintf(__('an unexpected error occurred (%s)', 'alt-context'), reason),
        fix: __('Retry. If it continues, check Settings and the service logs.', 'alt-context'),
      };
  }
};

const formatLastChecked = (checkedAt: string): string | null => {
  const milliseconds = Date.parse(checkedAt);
  if (!Number.isFinite(milliseconds)) {
    return null;
  }
  return new Date(milliseconds).toISOString().slice(11, 19);
};

const retryCountdownSeconds = (retryAfterSeconds: number | null): number | null => {
  if (retryAfterSeconds === null || !Number.isFinite(retryAfterSeconds) || retryAfterSeconds <= 0) {
    return null;
  }
  return Math.floor(retryAfterSeconds);
};

export const RetentionSection = (): React.JSX.Element => {
  const {
    state,
    dispatch,
    importFileRef,
    retentionQuery,
    exportJobStatus,
    status,
    policy,
    selectedMode,
    isPolicyDirty,
    modeDescription,
    pending,
    actions,
  } = useRetentionPageState();

  const exportFailed = state.exportJobId !== null && exportJobStatus === EXPORT_JOB_STATUS.failed;
  const exportStatusText =
    state.exportJobId === null || exportFailed
      ? ''
      : exportJobStatus === EXPORT_JOB_STATUS.completed
        ? sprintf(__('Export completed. Job ID: %s', 'alt-context'), state.exportJobId)
        : sprintf(__('Export in progress… Job ID: %s', 'alt-context'), state.exportJobId);
  const exportErrorText =
    state.exportJobId !== null && exportJobStatus === EXPORT_JOB_STATUS.failed
      ? sprintf(__('Export failed. Please try again. Job ID: %s', 'alt-context'), state.exportJobId)
      : '';

  const unavailable = readUnavailable(status);
  const unavailableService = unavailable ? unavailableServiceLabel(unavailable.service) : null;
  const unavailableCopy = unavailable ? unavailableReasonCopy(unavailable.reason) : null;
  const lastChecked = unavailable ? formatLastChecked(unavailable.checked_at) : null;
  const retryInSeconds = unavailable ? retryCountdownSeconds(unavailable.retry_after_seconds) : null;

  const body = retentionQuery.isLoading ? (
    <p>{__('Loading retention status\u2026', 'alt-context')}</p>
  ) : retentionQuery.isError || !status || !status.available || !policy ? (
    <section className="acx-dashboard__panel acx-retention__panel">
      {unavailable && unavailableService && unavailableCopy ? (
        <>
          <h4>{sprintf(__('%s unavailable', 'alt-context'), unavailableService)}</h4>
          <div
            className="acx-sync-status acx-sync-status--warning"
            role="alert"
            data-testid="acx-retention-unavailable"
          >
            <AlertTriangle
              className="acx-retention__note-icon"
              size={16}
              aria-hidden="true"
              data-testid="acx-retention-unavailable-icon"
            />
            <div>
              <p>
                {sprintf(
                  __('%s is unavailable because %s.', 'alt-context'),
                  unavailableService,
                  unavailableCopy.why,
                )}
              </p>
              <p>{unavailableCopy.fix}</p>
              {lastChecked ? (
                <p className="acx-retention__detail">
                  {sprintf(__('Last checked %s', 'alt-context'), lastChecked)}
                </p>
              ) : null}
              {retryInSeconds !== null ? (
                <p className="acx-retention__detail">
                  {sprintf(__('Retry in %d s', 'alt-context'), retryInSeconds)}
                </p>
              ) : null}
            </div>
          </div>
        </>
      ) : (
        <>
          <h4>{__('Backend unavailable', 'alt-context')}</h4>
          <p>{__('Backend unavailable \u2014 retention status cannot be loaded.', 'alt-context')}</p>
          {retentionQuery.isError ? (
            <p role="alert">
              {toUserMessage(
                retentionQuery.error,
                __('Unable to load retention status. Please try again.', 'alt-context'),
              )}
            </p>
          ) : null}
        </>
      )}
      <button
        type="button"
        className="acx-button acx-button--secondary"
        onClick={() => void retentionQuery.refetch()}
        disabled={retentionQuery.isFetching}
        aria-busy={retentionQuery.isFetching}
      >
        {retentionQuery.isFetching ? __('Fetching…', 'alt-context') : __('Retry', 'alt-context')}
      </button>
      <p role="status" aria-live="polite">
        {retentionQuery.isFetching ? __('Fetching retention status…', 'alt-context') : ''}
      </p>
    </section>
  ) : (
    <>
      <div className="acx-retention__grid">
        <section className="acx-dashboard__panel acx-retention__panel">
          <h4>{__('Retention mode', 'alt-context')}</h4>
          <RadioGroup
            className="acx-retention__options"
            aria-label={__('Retention mode', 'alt-context')}
            value={selectedMode}
            onValueChange={(value) => dispatch({ type: 'SET_DRAFT_MODE', mode: value as RetentionMode })}
          >
            {RETENTION_OPTIONS.map((option) => (
              <label key={option.value} className="acx-retention__option">
                <RadioGroupItem value={option.value} aria-label={option.label} />
                <span>
                  <strong>{option.label}</strong>
                  <small>{option.description}</small>
                </span>
              </label>
            ))}
          </RadioGroup>
          <p className="acx-retention__detail">{modeDescription}</p>
          <p className="acx-retention__detail">
            {sprintf(__('Last policy update: %s', 'alt-context'), formatTimestamp(policy.retention_updated_at))}
          </p>
          <button
            type="button"
            className="acx-button acx-button--primary"
            disabled={!isPolicyDirty || pending.updatePolicy}
            onClick={() => void actions.savePolicy()}
          >
            {pending.updatePolicy ? __('Saving\u2026', 'alt-context') : __('Save policy', 'alt-context')}
          </button>
        </section>

        <section className="acx-dashboard__panel acx-retention__panel">
          <h4>{__('Compliance presets', 'alt-context')}</h4>
          <p>
            {__(
              'Apply a preset to configure recommended retention settings for common compliance scenarios.',
              'alt-context',
            )}
          </p>
          <div className="acx-retention__presets">
            <div className="acx-retention__preset-card">
              <strong>{__('GDPR mode', 'alt-context')}</strong>
              <p>
                {__(
                  'Sets retention mode to \u201cDispose after confirmation\u201d, automatically disposing machine-derived data after WordPress confirms results.',
                  'alt-context',
                )}
              </p>
              <button
                type="button"
                className="acx-button acx-button--secondary"
                disabled={pending.applyPreset}
                onClick={() => void actions.applyGdprPreset()}
              >
                {pending.applyPreset ? __('Applying\u2026', 'alt-context') : __('Apply GDPR preset', 'alt-context')}
              </button>
            </div>
          </div>
        </section>

        <section className="acx-dashboard__panel acx-retention__panel">
          <h4>{__('Export controls', 'alt-context')}</h4>
          <p>
            {__(
              'Export face groups, members, detection metadata, and representative details as portable JSON.',
              'alt-context',
            )}
          </p>
          <p className="acx-retention__detail">
            {sprintf(__('Last export: %s', 'alt-context'), formatTimestamp(policy.last_export_at))}
          </p>
          <p className="acx-retention__note">{__('Raw embedding vectors are excluded from exports.', 'alt-context')}</p>
          <div
            className={exportStatusText ? 'acx-retention__detail' : undefined}
            role="status"
            aria-live="polite"
          >
            {exportStatusText}
          </div>
          <div
            className={exportErrorText ? 'acx-retention__detail' : undefined}
            role="alert"
            aria-live="assertive"
          >
            {exportErrorText}
          </div>
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={() => dispatch({ type: 'OPEN_EXPORT_DIALOG' })}
          >
            {__('Export data', 'alt-context')}
          </button>
        </section>

        <section className="acx-dashboard__panel acx-retention__panel">
          <h4>{__('Purge controls', 'alt-context')}</h4>
          <p>
            {__(
              'Purge permanently deletes disposed state or all machine-derived tenant data from the backend.',
              'alt-context',
            )}
          </p>
          <p className="acx-retention__detail">
            {sprintf(__('Last purge: %s', 'alt-context'), formatTimestamp(policy.last_purge_at))}
          </p>
          <p className="acx-retention__note acx-retention__note--danger">
            <AlertTriangle
              className="acx-retention__note-icon"
              size={16}
              aria-hidden="true"
              data-testid="acx-retention-danger-icon"
            />
            <span>
              {__('This action is irreversible and should be used carefully.', 'alt-context')}
            </span>
          </p>
          <button
            type="button"
            className="acx-button acx-button--danger"
            onClick={() => dispatch({ type: 'OPEN_PURGE_DIALOG' })}
          >
            {__('Purge data', 'alt-context')}
          </button>
        </section>

        <section className="acx-dashboard__panel acx-retention__panel">
          <h4>{__('Import controls', 'alt-context')}</h4>
          <p>
            {__(
              'Restore tenant state from a previously exported JSON file. The import validates schema compatibility and records a lifecycle audit event.',
              'alt-context',
            )}
          </p>
          <p className="acx-retention__note">
            {__('Raw embedding vectors are not included in exports and will not be restored.', 'alt-context')}
          </p>
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={() => dispatch({ type: 'OPEN_IMPORT_DIALOG' })}
          >
            {__('Import data', 'alt-context')}
          </button>
        </section>

        <section className="acx-dashboard__panel acx-retention__panel">
          <h4>{__('Description history', 'alt-context')}</h4>
          <p>
            {__(
              'Description Runs is the home for describer history. Data Retention keeps policy, export, and purge only.',
              'alt-context',
            )}
          </p>
          <a className="acx-button acx-button--secondary" href={toDescriptionHistory()}>
            {__('See description run history', 'alt-context')}
          </a>
        </section>
      </div>

      <ExportDialog
        open={state.isExportDialogOpen}
        dispatch={dispatch}
        exportJobId={state.exportJobId}
        exportJobStatus={exportJobStatus}
        isExportPending={pending.export}
        isDownloadPending={pending.download}
        onStartExport={() => void actions.confirmExport()}
        onDownloadExport={() => void actions.downloadExport()}
      />
      <PurgeDialog
        open={state.isPurgeDialogOpen}
        dispatch={dispatch}
        purgeScope={state.purgeScope}
        purgeConfirmation={state.purgeConfirmation}
        isPurgePending={pending.purge}
        onConfirmPurge={() => void actions.confirmPurge()}
      />
      <ImportDialog
        open={state.isImportDialogOpen}
        dispatch={dispatch}
        importFile={state.importFile}
        importFileRef={importFileRef}
        isImportPending={pending.import}
        onConfirmImport={() => void actions.confirmImport()}
      />
    </>
  );

  return (
    <section className="acx-retention" aria-labelledby="acx-retention-title">
      <h3 id="acx-retention-title" className="acx-settings__section-title" tabIndex={-1}>
        {__('Data & retention', 'alt-context')}
      </h3>
      {body}
    </section>
  );
};

export const RetentionPage = RetentionSection;
