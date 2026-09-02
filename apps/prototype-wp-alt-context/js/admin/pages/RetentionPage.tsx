import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { AlertTriangle } from 'lucide-react';

import { RadioGroup, RadioGroupItem } from '../../components/ui/radio-group';
import type { RetentionMode } from '../api/recognition';
import { useRetentionPageState, RETENTION_OPTIONS } from './retention/useRetentionPageState';
import { ExportDialog, PurgeDialog, ImportDialog } from './retention/RetentionDialogs';
import { formatTimestamp } from './retention/AuditTimeline';
import { toDescriptionHistory } from '../navigation/appLinks';

const EXPORT_JOB_STATUS = {
  completed: 'completed',
  failed: 'failed',
} as const;

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

  if (retentionQuery.isLoading) {
    return (
      <section className="acx-retention" aria-labelledby="acx-retention-title">
        <h1 id="acx-retention-title" className="acx-dashboard__title">{__('Data Retention', 'alt-context')}</h1>
        <p>{__('Loading retention status\u2026', 'alt-context')}</p>
      </section>
    );
  }

  if (retentionQuery.isError || !status || !status.available || !policy) {
    return (
      <section className="acx-retention" aria-labelledby="acx-retention-title">
        <header className="acx-retention__hero">
          <p className="acx-dashboard__eyebrow">{__('Governance', 'alt-context')}</p>
          <h1 id="acx-retention-title" className="acx-dashboard__title">
            {__('Data Retention', 'alt-context')}
          </h1>
          <p className="acx-dashboard__subtitle">
            {__('Review your data and retention, export machine-derived data, and audit lifecycle actions.', 'alt-context')}
          </p>
        </header>
        <section className="acx-dashboard__panel acx-retention__panel">
          <h2>{__('Backend unavailable', 'alt-context')}</h2>
          <p>{__('Backend unavailable \u2014 retention status cannot be loaded.', 'alt-context')}</p>
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={() => void retentionQuery.refetch()}
          >
            {__('Retry', 'alt-context')}
          </button>
        </section>
      </section>
    );
  }

  return (
    <section className="acx-retention" aria-labelledby="acx-retention-title">
      <header className="acx-retention__hero">
        <p className="acx-dashboard__eyebrow">{__('Governance', 'alt-context')}</p>
        <h1 id="acx-retention-title" className="acx-dashboard__title">
          {__('Data Retention', 'alt-context')}
        </h1>
        <p className="acx-dashboard__subtitle">
          {__('Review your data and retention, export machine-derived data, and audit lifecycle actions.', 'alt-context')}
        </p>
      </header>

      <div className="acx-retention__grid">
        <section className="acx-dashboard__panel acx-retention__panel">
          <h2>{__('Retention mode', 'alt-context')}</h2>
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
          <h2>{__('Compliance presets', 'alt-context')}</h2>
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
          <h2>{__('Export controls', 'alt-context')}</h2>
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
          <h2>{__('Purge controls', 'alt-context')}</h2>
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
          <h2>{__('Import controls', 'alt-context')}</h2>
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
          <h2>{__('Description history', 'alt-context')}</h2>
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
    </section>
  );
};

export const RetentionPage = RetentionSection;
