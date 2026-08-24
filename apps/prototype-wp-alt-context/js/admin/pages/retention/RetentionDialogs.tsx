import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../components/ui/dialog';
import { RadioGroup, RadioGroupItem } from '../../../components/ui/radio-group';
import { PURGE_DIALOG_DESCRIPTION, PURGE_SCOPE_OPTIONS } from './retentionDialogCopy';
import type { RetentionAction } from './useRetentionPageState';

const RETENTION_CONFIRM_PHRASE = 'PURGE';

const EXPORT_JOB_STATUS = {
  completed: 'completed',
  failed: 'failed',
} as const;

/* ------------------------------------------------------------------ */
/*  Export Dialog                                                       */
/* ------------------------------------------------------------------ */

interface ExportDialogProps {
  open: boolean;
  dispatch: React.Dispatch<RetentionAction>;
  exportJobId: string | null;
  exportJobStatus: string | null;
  isExportPending: boolean;
  isDownloadPending: boolean;
  onStartExport: () => void;
  onDownloadExport: () => void;
}

export const ExportDialog = ({
  open,
  dispatch,
  exportJobId,
  exportJobStatus,
  isExportPending,
  isDownloadPending,
  onStartExport,
  onDownloadExport,
}: ExportDialogProps): React.JSX.Element => {
  const closeDialog = React.useCallback(() => {
    dispatch({ type: 'CLOSE_EXPORT_DIALOG' });
  }, [dispatch]);

  const handleOpenChange = React.useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        closeDialog();
      }
    },
    [closeDialog],
  );

  return (
    <DialogRoot open={open} onOpenChange={handleOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogContent>
          <DialogTitle>{__('Export tenant data', 'alt-context')}</DialogTitle>
          <DialogDescription>
            {__(
              'This export includes clusters, members, detection metadata, and representative details. Raw embedding vectors are excluded.',
              'alt-context',
            )}
          </DialogDescription>
          <div className="acx-dialog__actions">
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={closeDialog}
              disabled={isExportPending || isDownloadPending}
            >
              {__('Close', 'alt-context')}
            </button>
            {exportJobId !== null && exportJobStatus === EXPORT_JOB_STATUS.completed ? (
              <button
                type="button"
                className="acx-button acx-button--primary"
                onClick={onDownloadExport}
                disabled={isDownloadPending}
              >
                {isDownloadPending ? __('Downloading\u2026', 'alt-context') : __('Download export', 'alt-context')}
              </button>
            ) : (
              <button
                type="button"
                className="acx-button acx-button--primary"
                onClick={onStartExport}
                disabled={isExportPending || exportJobId !== null}
              >
                {isExportPending ? __('Starting\u2026', 'alt-context') : __('Start export', 'alt-context')}
              </button>
            )}
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};

/* ------------------------------------------------------------------ */
/*  Purge Dialog                                                       */
/* ------------------------------------------------------------------ */

interface PurgeDialogProps {
  open: boolean;
  dispatch: React.Dispatch<RetentionAction>;
  purgeScope: 'disposed' | 'all';
  purgeConfirmation: string;
  isPurgePending: boolean;
  onConfirmPurge: () => void;
}

export const PurgeDialog = ({
  open,
  dispatch,
  purgeScope,
  purgeConfirmation,
  isPurgePending,
  onConfirmPurge,
}: PurgeDialogProps): React.JSX.Element => {
  const handleOpenChange = React.useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        dispatch({ type: 'CLOSE_PURGE_DIALOG' });
      }
    },
    [dispatch],
  );

  return (
    <DialogRoot open={open} onOpenChange={handleOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogContent>
          <DialogTitle>{__('Purge tenant data', 'alt-context')}</DialogTitle>
          <DialogDescription>{PURGE_DIALOG_DESCRIPTION}</DialogDescription>
          <RadioGroup
            className="acx-retention__dialog-fieldset"
            aria-label={__('Purge scope', 'alt-context')}
            value={purgeScope}
            onValueChange={(value: string) => dispatch({ type: 'SET_PURGE_SCOPE', scope: value as 'disposed' | 'all' })}
          >
            {PURGE_SCOPE_OPTIONS.map((option) => (
              <label key={option.value} className="acx-retention__option">
                <RadioGroupItem value={option.value} aria-label={option.label} />
                <span>
                  <strong>{option.label}</strong>
                  <small>{option.description}</small>
                </span>
              </label>
            ))}
          </RadioGroup>
          <label className="acx-retention__confirm-input">
            <span>{sprintf(__('Type %s to confirm this purge.', 'alt-context'), RETENTION_CONFIRM_PHRASE)}</span>
            <input
              type="text"
              value={purgeConfirmation}
              onChange={(event) => dispatch({ type: 'SET_PURGE_CONFIRMATION', text: event.target.value })}
            />
          </label>
          <div className="acx-dialog__actions">
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={() => dispatch({ type: 'CLOSE_PURGE_DIALOG' })}
              disabled={isPurgePending}
            >
              {__('Cancel', 'alt-context')}
            </button>
            <button
              type="button"
              className="acx-button acx-button--danger"
              onClick={onConfirmPurge}
              disabled={isPurgePending || purgeConfirmation !== RETENTION_CONFIRM_PHRASE}
            >
              {isPurgePending ? __('Purging\u2026', 'alt-context') : __('Confirm purge', 'alt-context')}
            </button>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};

/* ------------------------------------------------------------------ */
/*  Import Dialog                                                      */
/* ------------------------------------------------------------------ */

interface ImportDialogProps {
  open: boolean;
  dispatch: React.Dispatch<RetentionAction>;
  importFile: File | null;
  importFileRef: React.RefObject<HTMLInputElement>;
  isImportPending: boolean;
  onConfirmImport: () => void;
}

export const ImportDialog = ({
  open,
  dispatch,
  importFile,
  importFileRef,
  isImportPending,
  onConfirmImport,
}: ImportDialogProps): React.JSX.Element => {
  const handleOpenChange = React.useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        dispatch({ type: 'CLOSE_IMPORT_DIALOG' });
        if (importFileRef.current) {
          importFileRef.current.value = '';
        }
      }
    },
    [dispatch, importFileRef],
  );

  return (
    <DialogRoot open={open} onOpenChange={handleOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogContent>
          <DialogTitle>{__('Import tenant data', 'alt-context')}</DialogTitle>
          <DialogDescription>
            {__(
              'Select a JSON export file to validate and record as an import event. Schema version compatibility is verified before import.',
              'alt-context',
            )}
          </DialogDescription>
          <label className="acx-retention__file-input">
            <span>{__('Export file (.json)', 'alt-context')}</span>
            <input
              ref={importFileRef}
              type="file"
              accept="application/json,.json"
              onChange={(event) => dispatch({ type: 'SET_IMPORT_FILE', file: event.target.files?.[0] ?? null })}
            />
          </label>
          {importFile && (
            <p className="acx-retention__detail">{sprintf(__('Selected: %s', 'alt-context'), importFile.name)}</p>
          )}
          <div className="acx-dialog__actions">
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={() => dispatch({ type: 'CLOSE_IMPORT_DIALOG' })}
              disabled={isImportPending}
            >
              {__('Cancel', 'alt-context')}
            </button>
            <button
              type="button"
              className="acx-button acx-button--primary"
              onClick={onConfirmImport}
              disabled={isImportPending || !importFile}
            >
              {isImportPending ? __('Importing\u2026', 'alt-context') : __('Import', 'alt-context')}
            </button>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};
