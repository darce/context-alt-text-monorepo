import { useReducer, useRef } from 'react';
import { __ } from '@wordpress/i18n';

import type { RetentionExportResponse, RetentionMode, StartExportJobResponse } from '../../api/recognition';
import { useToast } from '../../context/ToastContext';
import { useRetentionPageMutations } from './useRetentionPageMutations';
import { useRetentionPageQueries } from './useRetentionPageQueries';

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

export const RETENTION_OPTIONS: { value: RetentionMode; label: string; description: string }[] = [
  {
    value: 'retain_all',
    label: __('Retain all', 'alt-context'),
    description: __('Keep embeddings and clustering state until an operator explicitly changes policy.', 'alt-context'),
  },
  {
    value: 'dispose_after_ack',
    label: __('Dispose after confirmation', 'alt-context'),
    description: __('Mark machine-derived working state for disposal once WordPress confirms results.', 'alt-context'),
  },
  {
    value: 'purge_on_demand',
    label: __('Purge on demand', 'alt-context'),
    description: __('Retain state until an operator triggers a purge action from this page.', 'alt-context'),
  },
];

const AUDIT_PAGE_SIZE = 20;
export { AUDIT_PAGE_SIZE };

/* ------------------------------------------------------------------ */
/*  Reducer                                                            */
/* ------------------------------------------------------------------ */

export interface RetentionDialogState {
  draftMode: RetentionMode | null;
  isExportDialogOpen: boolean;
  exportJobId: string | null;
  isPurgeDialogOpen: boolean;
  purgeScope: 'disposed' | 'all';
  purgeConfirmation: string;
  isImportDialogOpen: boolean;
  importFile: File | null;
  auditPage: number;
}

export type RetentionAction =
  | { type: 'SET_DRAFT_MODE'; mode: RetentionMode | null }
  | { type: 'OPEN_EXPORT_DIALOG' }
  | { type: 'CLOSE_EXPORT_DIALOG' }
  | { type: 'SET_EXPORT_JOB_ID'; jobId: string | null }
  | { type: 'OPEN_PURGE_DIALOG' }
  | { type: 'CLOSE_PURGE_DIALOG' }
  | { type: 'SET_PURGE_SCOPE'; scope: 'disposed' | 'all' }
  | { type: 'SET_PURGE_CONFIRMATION'; text: string }
  | { type: 'OPEN_IMPORT_DIALOG' }
  | { type: 'CLOSE_IMPORT_DIALOG' }
  | { type: 'SET_IMPORT_FILE'; file: File | null }
  | { type: 'SET_AUDIT_PAGE'; page: number };

const initialState: RetentionDialogState = {
  draftMode: null,
  isExportDialogOpen: false,
  exportJobId: null,
  isPurgeDialogOpen: false,
  purgeScope: 'disposed',
  purgeConfirmation: '',
  isImportDialogOpen: false,
  importFile: null,
  auditPage: 0,
};

export const retentionReducer = (state: RetentionDialogState, action: RetentionAction): RetentionDialogState => {
  switch (action.type) {
    case 'SET_DRAFT_MODE':
      return { ...state, draftMode: action.mode };
    case 'OPEN_EXPORT_DIALOG':
      return { ...state, isExportDialogOpen: true };
    case 'CLOSE_EXPORT_DIALOG':
      // The export API does not expose cancellation. Closing is presentation
      // only, so retain the job id and keep polling for a truthful status when
      // the operator reopens the dialog.
      return { ...state, isExportDialogOpen: false };
    case 'SET_EXPORT_JOB_ID':
      return { ...state, exportJobId: action.jobId };
    case 'OPEN_PURGE_DIALOG':
      return { ...state, isPurgeDialogOpen: true };
    case 'CLOSE_PURGE_DIALOG':
      return { ...state, isPurgeDialogOpen: false, purgeScope: 'disposed', purgeConfirmation: '' };
    case 'SET_PURGE_SCOPE':
      return { ...state, purgeScope: action.scope };
    case 'SET_PURGE_CONFIRMATION':
      return { ...state, purgeConfirmation: action.text };
    case 'OPEN_IMPORT_DIALOG':
      return { ...state, isImportDialogOpen: true };
    case 'CLOSE_IMPORT_DIALOG':
      return { ...state, isImportDialogOpen: false, importFile: null };
    case 'SET_IMPORT_FILE':
      return { ...state, importFile: action.file };
    case 'SET_AUDIT_PAGE':
      return { ...state, auditPage: action.page };
  }
};

/* ------------------------------------------------------------------ */
/*  Utilities                                                          */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

export const useRetentionPageState = () => {
  const { success, error: showError } = useToast();
  const [state, dispatch] = useReducer(retentionReducer, initialState);
  const importFileRef = useRef<HTMLInputElement>(null);
  const { retentionQuery, exportJobStatusQuery, auditQuery } = useRetentionPageQueries(
    state.exportJobId,
    state.auditPage,
    AUDIT_PAGE_SIZE,
  );
  const { updatePolicy, exportMutation, purgeMutation, importMutation, applyPreset, downloadJobData } =
    useRetentionPageMutations();

  const status = retentionQuery.data;
  const policy = status?.policy ?? null;
  const selectedMode = state.draftMode ?? policy?.retention_mode ?? 'retain_all';
  const isPolicyDirty = Boolean(policy && selectedMode !== policy.retention_mode);
  const auditEvents = status?.recent_audit_events ?? [];
  const exportJobStatus = exportJobStatusQuery.data?.status ?? null;
  const modeDescription = RETENTION_OPTIONS.find((option) => option.value === selectedMode)?.description ?? '';

  const savePolicy = async (): Promise<void> => {
    if (!policy || !isPolicyDirty) {
      return;
    }
    try {
      await updatePolicy.mutateAsync({ retention_mode: selectedMode });
      dispatch({ type: 'SET_DRAFT_MODE', mode: null });
      success(__('Retention policy updated.', 'alt-context'));
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to update retention policy.', 'alt-context'));
    }
  };

  const confirmExport = async (): Promise<void> => {
    try {
      const result: StartExportJobResponse = await exportMutation.mutateAsync();
      dispatch({ type: 'SET_EXPORT_JOB_ID', jobId: result.job_id });
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to start export.', 'alt-context'));
    }
  };

  const downloadExport = async (): Promise<void> => {
    if (!state.exportJobId) {
      return;
    }
    try {
      const response = await downloadJobData.mutateAsync(state.exportJobId);
      downloadExportPayload(response);
      dispatch({ type: 'SET_EXPORT_JOB_ID', jobId: null });
      dispatch({ type: 'CLOSE_EXPORT_DIALOG' });
      success(__('Tenant export downloaded.', 'alt-context'));
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to download export data.', 'alt-context'));
    }
  };

  const confirmPurge = async (): Promise<void> => {
    try {
      await purgeMutation.mutateAsync({ scope: state.purgeScope, confirm: true });
      dispatch({ type: 'CLOSE_PURGE_DIALOG' });
      success(__('Tenant purge completed.', 'alt-context'));
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to purge tenant data.', 'alt-context'));
    }
  };

  const confirmImport = async (): Promise<void> => {
    if (!state.importFile) {
      return;
    }
    try {
      const text = await state.importFile.text();
      const parsed: unknown = JSON.parse(text);
      if (!parsed || typeof parsed !== 'object') {
        throw new Error(__('Invalid export file: expected a JSON object.', 'alt-context'));
      }
      const data = parsed as Record<string, unknown>;
      await importMutation.mutateAsync({ data });
      dispatch({ type: 'CLOSE_IMPORT_DIALOG' });
      if (importFileRef.current) {
        importFileRef.current.value = '';
      }
      success(__('Import completed.', 'alt-context'));
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to import data.', 'alt-context'));
    }
  };

  const applyGdprPreset = async (): Promise<void> => {
    try {
      await applyPreset.mutateAsync({ preset: 'gdpr' });
      dispatch({ type: 'SET_DRAFT_MODE', mode: null });
      success(__('GDPR preset applied.', 'alt-context'));
    } catch (error) {
      showError(error instanceof Error ? error.message : __('Unable to apply preset.', 'alt-context'));
    }
  };

  return {
    state,
    dispatch,
    importFileRef,
    retentionQuery,
    auditQuery,
    exportJobStatus,
    status,
    policy,
    selectedMode,
    isPolicyDirty,
    auditEvents,
    modeDescription,
    pending: {
      updatePolicy: updatePolicy.isPending,
      export: exportMutation.isPending,
      purge: purgeMutation.isPending,
      import: importMutation.isPending,
      applyPreset: applyPreset.isPending,
      download: downloadJobData.isPending,
    },
    actions: {
      savePolicy,
      confirmExport,
      downloadExport,
      confirmPurge,
      confirmImport,
      applyGdprPreset,
    },
  };
};

export type RetentionPageStateReturn = ReturnType<typeof useRetentionPageState>;
