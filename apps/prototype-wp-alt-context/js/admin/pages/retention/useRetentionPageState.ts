import { useReducer, useRef } from 'react';
import { __ } from '@wordpress/i18n';

import {
  EXPORT_COLLECTION_KEYS,
  RetentionExportResponseError,
  type RetentionExportResponse,
  type RetentionMode,
  type StartExportJobResponse,
} from '../../api/recognition';
import { useToast } from '../../context/ToastContext';
import { toUserMessage } from '../../utils/appError';
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
    description: __(
      'Mark machine-derived working state for disposal once WordPress confirms results.',
      'alt-context',
    ),
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

/**
 * Top-level collection keys carried by a recognition tenant-export snapshot.
 *
 * sr-007/rg-005: the canonical definition lives next to the boundary adapter
 * that also validates them (`api/recognition/retentionApi.ts`), which mirrors
 * `IMPORT_COLLECTION_KEYS` in
 * `recognition/application/services/import_service.py`. Re-exported here for
 * the existing consumers of this module; do not fork a second copy.
 */
export { EXPORT_COLLECTION_KEYS };

/** Locally authored, safe-to-display boundary rejection (never carries remote text). */
export class RetentionImportValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RetentionImportValidationError';
  }
}

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Validate a user-supplied export file and return the snapshot the backend expects.
 *
 * Boundary data, so it is validated explicitly rather than with a TS assertion
 * helper (sr-005). Fail Fast ("Release It!"): a malformed snapshot is rejected
 * here, before a request is issued, instead of being accepted as an empty import.
 *
 * `downloadExportPayload` writes `{ tenant_id, exported_at, schema_version,
 * counts, data: <snapshot> }`. The import contract is `{ data: <snapshot> }`, so
 * the envelope must be unwrapped; a bare snapshot (no `data` key) is also accepted.
 */
export const extractImportSnapshot = (parsed: unknown): Record<string, unknown> => {
  if (Array.isArray(parsed)) {
    throw new RetentionImportValidationError(
      __('Invalid export file: expected a JSON object, not an array.', 'alt-context'),
    );
  }
  if (!isPlainObject(parsed)) {
    throw new RetentionImportValidationError(
      __('Invalid export file: expected a JSON object.', 'alt-context'),
    );
  }

  const snapshot = isPlainObject(parsed.data) ? parsed.data : parsed;

  if (!Number.isInteger(snapshot.schema_version)) {
    throw new RetentionImportValidationError(
      __('Invalid export file: missing or non-integer schema_version.', 'alt-context'),
    );
  }

  const presentKeys = EXPORT_COLLECTION_KEYS.filter((key) => key in snapshot);
  if (presentKeys.length === 0) {
    throw new RetentionImportValidationError(
      __('Invalid export file: no exported collections found.', 'alt-context'),
    );
  }
  for (const key of presentKeys) {
    if (!Array.isArray(snapshot[key])) {
      throw new RetentionImportValidationError(
        __('Invalid export file: exported collections must be arrays.', 'alt-context'),
      );
    }
  }

  return snapshot;
};

/**
 * The envelope written to disk by `downloadExport`; the snapshot lives under `data`.
 *
 * `schema_version` is written unconditionally: `downloadExportJobData` rejects any
 * snapshot without an integer `schema_version`, so a `RetentionExportResponse`
 * always carries one. The former `typeof … === 'number'` guard was dead code that
 * read as if the field were optional and quietly allowed a schema-less file to be
 * written to disk — one an operator could only discover on a later import.
 * `tenant_id` / `exported_at` keep their guards: those are genuinely optional.
 */
export const buildExportDocument = (response: RetentionExportResponse): Record<string, unknown> => ({
  ...(response.tenant_id ? { tenant_id: response.tenant_id } : {}),
  ...(response.exported_at ? { exported_at: response.exported_at } : {}),
  schema_version: response.schema_version,
  counts: response.summary,
  data: response.payload,
});

/**
 * Write the export document to disk via a transient object URL.
 *
 * RES-04/RES-20: the scope that acquires the object URL and the detached
 * anchor releases both on every path, including when `click()` throws — an
 * object URL that is never revoked pins its blob for the lifetime of the
 * document. Exported so the release path is directly testable (jsdom does not
 * implement `URL.createObjectURL`, so the test stubs it).
 */
export const downloadExportPayload = (response: RetentionExportResponse): void => {
  const exportDocument = buildExportDocument(response);
  const blob = new Blob([JSON.stringify(exportDocument, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `alt-context-retention-export-${new Date().toISOString()}.json`;
    document.body.append(anchor);
    try {
      anchor.click();
    } finally {
      anchor.remove();
    }
  } finally {
    URL.revokeObjectURL(url);
  }
};

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

export const useRetentionPageState = () => {
  const { success, error: showError } = useToast();
  const [state, dispatch] = useReducer(retentionReducer, initialState);
  const importFileRef = useRef<HTMLInputElement>(null);
  const { retentionQuery, exportJobStatusQuery } = useRetentionPageQueries(state.exportJobId);
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
      showError(toUserMessage(error, __('Unable to update retention policy.', 'alt-context')));
    }
  };

  const confirmExport = async (): Promise<void> => {
    try {
      const result: StartExportJobResponse = await exportMutation.mutateAsync();
      dispatch({ type: 'SET_EXPORT_JOB_ID', jobId: result.job_id });
    } catch (error) {
      showError(toUserMessage(error, __('Unable to start export.', 'alt-context')));
    }
  };

  const downloadExport = async (): Promise<void> => {
    if (!state.exportJobId) {
      return;
    }
    try {
      const response = await downloadJobData.mutateAsync(state.exportJobId);
      downloadExportPayload(response);
      dispatch({ type: 'CLOSE_EXPORT_DIALOG' });
      success(__('Tenant export downloaded.', 'alt-context'));
    } catch (error) {
      if (error instanceof RetentionExportResponseError) {
        showError(__('The export data returned by the server was malformed; nothing was downloaded.', 'alt-context'));
        return;
      }
      showError(toUserMessage(error, __('Unable to download export data.', 'alt-context')));
    }
  };

  const confirmPurge = async (): Promise<void> => {
    try {
      await purgeMutation.mutateAsync({ scope: state.purgeScope, confirm: true });
      dispatch({ type: 'CLOSE_PURGE_DIALOG' });
      success(__('Tenant purge completed.', 'alt-context'));
    } catch (error) {
      showError(toUserMessage(error, __('Unable to purge tenant data.', 'alt-context')));
    }
  };

  const confirmImport = async (): Promise<void> => {
    if (!state.importFile) {
      return;
    }
    try {
      const text = await state.importFile.text();
      const parsed: unknown = JSON.parse(text);
      const data = extractImportSnapshot(parsed);
      await importMutation.mutateAsync({ data });
      dispatch({ type: 'CLOSE_IMPORT_DIALOG' });
      if (importFileRef.current) {
        importFileRef.current.value = '';
      }
      success(__('Import completed.', 'alt-context'));
    } catch (error) {
      if (error instanceof RetentionImportValidationError) {
        showError(error.message);
        return;
      }
      showError(toUserMessage(error, __('Unable to import data.', 'alt-context')));
    }
  };

  const applyGdprPreset = async (): Promise<void> => {
    try {
      await applyPreset.mutateAsync({ preset: 'gdpr' });
      dispatch({ type: 'SET_DRAFT_MODE', mode: null });
      success(__('GDPR preset applied.', 'alt-context'));
    } catch (error) {
      showError(toUserMessage(error, __('Unable to apply preset.', 'alt-context')));
    }
  };

  return {
    state,
    dispatch,
    importFileRef,
    retentionQuery,
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
