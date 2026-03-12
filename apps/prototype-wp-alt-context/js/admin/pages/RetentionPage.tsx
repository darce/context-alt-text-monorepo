import React, { useMemo, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../components/ui/dialog';
import type { AuditEvent, RetentionExportResponse, RetentionMode } from '../api/recognition';
import {
  useExportTenantData,
  usePurgeTenantData,
  useRetentionStatus,
  useUpdateRetentionPolicy,
} from '../hooks/useRetentionStatus';
import { useToast } from '../context/ToastContext';

const RETENTION_CONFIRM_PHRASE = 'PURGE';

const RETENTION_OPTIONS: { value: RetentionMode; label: string; description: string }[] = [
  {
    value: 'retain_all',
    label: __('Retain all', 'alt-context'),
    description: __('Keep embeddings and clustering state until an operator explicitly changes policy.', 'alt-context'),
  },
  {
    value: 'dispose_after_ack',
    label: __('Dispose after acknowledgement', 'alt-context'),
    description: __('Mark machine-derived working state for disposal once WordPress acknowledges projection.', 'alt-context'),
  },
  {
    value: 'purge_on_demand',
    label: __('Purge on demand', 'alt-context'),
    description: __('Retain state until an operator triggers a purge action from this page.', 'alt-context'),
  },
];

const formatTimestamp = (value: string | null | undefined): string =>
  value ? new Date(value).toLocaleString() : __('Never', 'alt-context');

const summarizeAuditPayload = (event: AuditEvent): string => {
  const entries = Object.entries(event.payload ?? {}).filter(([, value]) => value !== null && value !== '');
  if (entries.length === 0) {
    return __('No payload details recorded.', 'alt-context');
  }

  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(' · ');
};

const downloadExportPayload = (response: RetentionExportResponse): void => {
  const exportDocument = {
    ...(response.tenant_id ? { tenant_id: response.tenant_id } : {}),
    ...(response.exported_at ? { exported_at: response.exported_at } : {}),
    ...(typeof response.schema_version === 'number' ? { schema_version: response.schema_version } : {}),
    counts: response.summary,
    data: response.payload,
  };
  const blob = new Blob([JSON.stringify(exportDocument, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `alt-context-retention-export-${new Date().toISOString()}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
};

export const RetentionPage = (): React.JSX.Element => {
  const { success, error: showError } = useToast();
  const retentionQuery = useRetentionStatus();
  const updatePolicy = useUpdateRetentionPolicy();
  const exportMutation = useExportTenantData();
  const purgeMutation = usePurgeTenantData();

  const [draftMode, setDraftMode] = useState<RetentionMode | null>(null);
  const [isExportDialogOpen, setExportDialogOpen] = useState(false);
  const [isPurgeDialogOpen, setPurgeDialogOpen] = useState(false);
  const [purgeScope, setPurgeScope] = useState<'disposed' | 'all'>('disposed');
  const [purgeConfirmation, setPurgeConfirmation] = useState('');

  const status = retentionQuery.data;
  const policy = status?.policy ?? null;
  const selectedMode = draftMode ?? policy?.retention_mode ?? 'retain_all';
  const isPolicyDirty = Boolean(policy && selectedMode !== policy.retention_mode);
  const auditEvents = status?.recent_audit_events ?? [];

  const modeDescription = useMemo(
    () => RETENTION_OPTIONS.find((option) => option.value === selectedMode)?.description ?? '',
    [selectedMode],
  );

  const savePolicy = async (): Promise<void> => {
    if (!policy || !isPolicyDirty) {
      return;
    }

    try {
      await updatePolicy.mutateAsync({ retention_mode: selectedMode });
      setDraftMode(null);
      success(__('Retention policy updated.', 'alt-context'));
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to update retention policy.', 'alt-context'));
    }
  };

  const confirmExport = async (): Promise<void> => {
    try {
      const response = await exportMutation.mutateAsync();
      downloadExportPayload(response);
      setExportDialogOpen(false);
      success(__('Tenant export generated and downloaded.', 'alt-context'));
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to export tenant data.', 'alt-context'));
    }
  };

  const confirmPurge = async (): Promise<void> => {
    try {
      await purgeMutation.mutateAsync({ scope: purgeScope, confirm: true });
      setPurgeDialogOpen(false);
      setPurgeConfirmation('');
      setPurgeScope('disposed');
      success(__('Tenant purge completed.', 'alt-context'));
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to purge tenant data.', 'alt-context'));
    }
  };

  if (retentionQuery.isLoading) {
    return (
      <section className="acx-retention" aria-labelledby="acx-retention-title">
        <h1 id="acx-retention-title">{__('Retention & Audit Controls', 'alt-context')}</h1>
        <p>{__('Loading retention status…', 'alt-context')}</p>
      </section>
    );
  }

  if (retentionQuery.isError || !status || !status.available || !policy) {
    return (
      <section className="acx-retention" aria-labelledby="acx-retention-title">
        <header className="acx-retention__hero">
          <p className="acx-dashboard__eyebrow">{__('Governance', 'alt-context')}</p>
          <h1 id="acx-retention-title" className="acx-dashboard__title">
            {__('Retention & Audit Controls', 'alt-context')}
          </h1>
          <p className="acx-dashboard__subtitle">
            {__('Review retention posture, export machine-derived data, and audit lifecycle actions.', 'alt-context')}
          </p>
        </header>
        <section className="acx-dashboard__panel acx-retention__panel">
          <h2>{__('Backend unavailable', 'alt-context')}</h2>
          <p>{__('Backend unavailable — retention status cannot be loaded.', 'alt-context')}</p>
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
          {__('Retention & Audit Controls', 'alt-context')}
        </h1>
        <p className="acx-dashboard__subtitle">
          {__('Review retention posture, export machine-derived data, and audit lifecycle actions.', 'alt-context')}
        </p>
      </header>

      <div className="acx-retention__grid">
        <section className="acx-dashboard__panel acx-retention__panel">
          <h2>{__('Retention mode', 'alt-context')}</h2>
          <fieldset className="acx-retention__options">
            <legend className="screen-reader-text">{__('Retention mode', 'alt-context')}</legend>
            {RETENTION_OPTIONS.map((option) => (
              <label key={option.value} className="acx-retention__option">
                <input
                  type="radio"
                  name="retention_mode"
                  value={option.value}
                  checked={selectedMode === option.value}
                  onChange={() => setDraftMode(option.value)}
                />
                <span>
                  <strong>{option.label}</strong>
                  <small>{option.description}</small>
                </span>
              </label>
            ))}
          </fieldset>
          <p className="acx-retention__detail">{modeDescription}</p>
          <p className="acx-retention__detail">
            {sprintf(__('Last policy update: %s', 'alt-context'), formatTimestamp(policy.retention_updated_at))}
          </p>
          <button
            type="button"
            className="acx-button acx-button--primary"
            disabled={!isPolicyDirty || updatePolicy.isPending}
            onClick={() => void savePolicy()}
          >
            {updatePolicy.isPending ? __('Saving…', 'alt-context') : __('Save policy', 'alt-context')}
          </button>
        </section>

        <section className="acx-dashboard__panel acx-retention__panel">
          <h2>{__('Export controls', 'alt-context')}</h2>
          <p>{__('Export clusters, members, detection metadata, and representative details as portable JSON.', 'alt-context')}</p>
          <p className="acx-retention__detail">
            {sprintf(__('Last export: %s', 'alt-context'), formatTimestamp(policy.last_export_at))}
          </p>
          <p className="acx-retention__note">
            {__('Raw embedding vectors are excluded from exports.', 'alt-context')}
          </p>
          <button type="button" className="acx-button acx-button--secondary" onClick={() => setExportDialogOpen(true)}>
            {__('Export data', 'alt-context')}
          </button>
        </section>

        <section className="acx-dashboard__panel acx-retention__panel">
          <h2>{__('Purge controls', 'alt-context')}</h2>
          <p>{__('Purge permanently deletes disposed state or all machine-derived tenant data from the backend.', 'alt-context')}</p>
          <p className="acx-retention__detail">
            {sprintf(__('Last purge: %s', 'alt-context'), formatTimestamp(policy.last_purge_at))}
          </p>
          <p className="acx-retention__note acx-retention__note--danger">
            {__('This action is irreversible and should be used carefully.', 'alt-context')}
          </p>
          <button type="button" className="acx-button acx-button--danger" onClick={() => setPurgeDialogOpen(true)}>
            {__('Purge data', 'alt-context')}
          </button>
        </section>

        <section className="acx-dashboard__panel acx-retention__panel acx-retention__panel--wide">
          <div className="acx-retention__panel-header">
            <h2 id="retention-audit-history">{__('Recent audit events', 'alt-context')}</h2>
            <span className="acx-retention__detail">
              {__('Showing the five most recent audit events.', 'alt-context')}
            </span>
          </div>
          {auditEvents.length === 0 ? (
            <p>{__('No audit events recorded yet.', 'alt-context')}</p>
          ) : (
            <ol className="acx-retention__timeline">
              {auditEvents.map((event) => (
                <li key={event.id} className="acx-retention__timeline-item">
                  <div className="acx-retention__timeline-heading">
                    <strong>{event.event_type}</strong>
                    <span>{formatTimestamp(event.created_at)}</span>
                  </div>
                  <p>{sprintf(__('Actor: %1$s · Result: %2$s', 'alt-context'), event.actor, event.result_status)}</p>
                  <p>{summarizeAuditPayload(event)}</p>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <DialogRoot open={isExportDialogOpen} onOpenChange={setExportDialogOpen}>
        <DialogPortal>
          <DialogOverlay />
          <DialogContent>
            <DialogTitle>{__('Export tenant data', 'alt-context')}</DialogTitle>
            <DialogDescription>
              {__('This export includes clusters, members, detection metadata, and representative details. Raw embedding vectors are excluded.', 'alt-context')}
            </DialogDescription>
            <div className="acx-dialog__actions">
              <button
                type="button"
                className="acx-button acx-button--secondary"
                onClick={() => setExportDialogOpen(false)}
                disabled={exportMutation.isPending}
              >
                {__('Cancel', 'alt-context')}
              </button>
              <button
                type="button"
                className="acx-button acx-button--primary"
                onClick={() => void confirmExport()}
                disabled={exportMutation.isPending}
              >
                {exportMutation.isPending ? __('Exporting…', 'alt-context') : __('Download export', 'alt-context')}
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>

      <DialogRoot open={isPurgeDialogOpen} onOpenChange={setPurgeDialogOpen}>
        <DialogPortal>
          <DialogOverlay />
          <DialogContent>
            <DialogTitle>{__('Purge tenant data', 'alt-context')}</DialogTitle>
            <DialogDescription>
              {__('Choose whether to purge only disposed state or all machine-derived tenant data. This cannot be undone.', 'alt-context')}
            </DialogDescription>
            <fieldset className="acx-retention__dialog-fieldset">
              <legend>{__('Purge scope', 'alt-context')}</legend>
              <label className="acx-retention__option">
                <input
                  type="radio"
                  name="purge_scope"
                  value="disposed"
                  checked={purgeScope === 'disposed'}
                  onChange={() => setPurgeScope('disposed')}
                />
                <span>
                  <strong>{__('Disposed only', 'alt-context')}</strong>
                  <small>{__('Delete rows already marked disposed after acknowledgement.', 'alt-context')}</small>
                </span>
              </label>
              <label className="acx-retention__option">
                <input
                  type="radio"
                  name="purge_scope"
                  value="all"
                  checked={purgeScope === 'all'}
                  onChange={() => setPurgeScope('all')}
                />
                <span>
                  <strong>{__('All machine data', 'alt-context')}</strong>
                  <small>{__('Delete all tenant embeddings, clusters, representatives, and related machine state.', 'alt-context')}</small>
                </span>
              </label>
            </fieldset>
            <label className="acx-retention__confirm-input">
              <span>
                {sprintf(__('Type %s to confirm this purge.', 'alt-context'), RETENTION_CONFIRM_PHRASE)}
              </span>
              <input
                type="text"
                value={purgeConfirmation}
                onChange={(event) => setPurgeConfirmation(event.target.value)}
              />
            </label>
            <div className="acx-dialog__actions">
              <button
                type="button"
                className="acx-button acx-button--secondary"
                onClick={() => setPurgeDialogOpen(false)}
                disabled={purgeMutation.isPending}
              >
                {__('Cancel', 'alt-context')}
              </button>
              <button
                type="button"
                className="acx-button acx-button--danger"
                onClick={() => void confirmPurge()}
                disabled={purgeMutation.isPending || purgeConfirmation !== RETENTION_CONFIRM_PHRASE}
              >
                {purgeMutation.isPending ? __('Purging…', 'alt-context') : __('Confirm purge', 'alt-context')}
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </section>
  );
};
