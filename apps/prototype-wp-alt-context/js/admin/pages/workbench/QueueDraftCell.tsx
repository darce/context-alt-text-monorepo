import { __, sprintf } from '@wordpress/i18n';
import { useEffect, useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import {
  DESCRIPTION_CORRECTION_CODE,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataBooleanField,
  resolveDescribeErrorDataField,
  resolveDescribeErrorMessage,
} from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';
import { QUEUE_DRAFTS_HISTORY_QUERY_KEY } from '../../hooks/useQueueDrafts';

export interface QueueDraftCellProps {
  mediaId: number;
  draftText: string;
  title?: string;
  onDismiss?: () => void;
  onApplied?: () => void;
  // Only the single focused-review surface should claim focus; table rows mount many cells.
  autoFocus?: boolean;
  /** Live row alt; omitted by standalone callers without a row baseline. */
  committedAlt?: string | null;
  peerCommitPending?: boolean;
  /** Synchronous exclusive claim; false means no correction may start. */
  onCommitStart?: () => boolean;
  onCommitEnd?: () => void;
}

const APPLY_ERROR_FALLBACK = __('Could not save the alt text. Please try again.', 'alt-context');
const DESCRIBE_RUN_ITEMS_QUERY_PREFIX = ['describe-run-items'] as const;
const COMMIT_CONFLICT_MESSAGE = __(
  'The alt text changed since this draft was shown. Your draft has been kept. Dismiss it and review a fresh draft.',
  'alt-context',
);
const COMMIT_BUSY_MESSAGE = __(
  'Another alt text save is in progress. Please try again when it finishes.',
  'alt-context',
);

/**
 * Inline draft chrome for one review-queue row. Accept/Save use the existing
 * per-media correction write (never bulk run apply, never auto-apply).
 */
export const QueueDraftCell = ({
  mediaId,
  draftText,
  title,
  onDismiss,
  onApplied,
  autoFocus = false,
  committedAlt,
  peerCommitPending = false,
  onCommitStart,
  onCommitEnd,
}: QueueDraftCellProps): React.JSX.Element | null => {
  const [isEditing, setIsEditing] = useState(false);
  const [editDraft, setEditDraft] = useState(draftText);
  const [dismissed, setDismissed] = useState(false);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);
  // The queue draft's first observed baseline survives peer saves, refetches,
  // and opening Edit. Rebase only for this cell's own reconciled partial write.
  const committedAltBaselineRef = useRef(committedAlt);
  const isApplyingRef = useRef(false);
  const shouldRestoreFocusRef = useRef(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const acceptButtonRef = useRef<HTMLButtonElement | null>(null);
  const editButtonRef = useRef<HTMLButtonElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const shouldFocusEditButtonRef = useRef(false);
  const textareaId = useId();
  const errorId = useId();
  const queryClient = useQueryClient();
  const { mutateAsync, isPending, error, reset } = useCorrectMediaAlt();
  const errorMessage = conflictMessage ?? (error ? resolveDescribeErrorMessage(error, APPLY_ERROR_FALLBACK) : null);

  const canAcceptDraft = draftText.trim() !== '';
  const canSaveEdit = editDraft.trim() !== '';
  const acceptLabel = title ? sprintf(__('Accept draft for %s', 'alt-context'), title) : __('Accept', 'alt-context');
  const editLabel = title ? sprintf(__('Edit draft for %s', 'alt-context'), title) : __('Edit draft', 'alt-context');

  useEffect(() => {
    if (!autoFocus) {
      return;
    }
    const active = document.activeElement;
    const ownsFocus = !active || active === document.body || containerRef.current?.contains(active);
    if (!ownsFocus) {
      return;
    }
    if (canAcceptDraft) {
      acceptButtonRef.current?.focus();
    } else {
      editButtonRef.current?.focus();
    }
  }, [autoFocus, canAcceptDraft]);

  useEffect(() => {
    if (isEditing) {
      textareaRef.current?.focus();
      return;
    }
    if (shouldFocusEditButtonRef.current) {
      shouldFocusEditButtonRef.current = false;
      editButtonRef.current?.focus();
    }
  }, [isEditing]);

  useEffect(() => {
    if (!isPending && shouldRestoreFocusRef.current) {
      shouldRestoreFocusRef.current = false;
      if (isEditing) {
        textareaRef.current?.focus();
      } else {
        acceptButtonRef.current?.focus();
      }
    }
  }, [isPending, isEditing, error]);

  if (dismissed) {
    return null;
  }

  const applyText = (altText: string): void => {
    if (isApplyingRef.current || isPending || peerCommitPending || altText.trim() === '') {
      return;
    }
    if (committedAltBaselineRef.current !== committedAlt) {
      setConflictMessage(COMMIT_CONFLICT_MESSAGE);
      if (isEditing) {
        textareaRef.current?.focus();
      }
      return;
    }
    if (!(onCommitStart?.() ?? true)) {
      setConflictMessage((current) => current ?? COMMIT_BUSY_MESSAGE);
      return;
    }
    setConflictMessage(null);
    isApplyingRef.current = true;
    void mutateAsync(
      { mediaId, altText },
      {
        onSuccess: () => {
          isApplyingRef.current = false;
          void queryClient.invalidateQueries({ queryKey: DESCRIBE_RUN_ITEMS_QUERY_PREFIX });
          void queryClient.invalidateQueries({ queryKey: QUEUE_DRAFTS_HISTORY_QUERY_KEY });
          onApplied?.();
          setDismissed(true);
        },
        onError: (err) => {
          isApplyingRef.current = false;
          // Match useCorrectMediaAlt's partial cache reconciliation. A retry
          // must not mistake its own stored write for a competing human save.
          if (resolveDescribeErrorCode(err) === DESCRIPTION_CORRECTION_CODE.PARTIAL) {
            const stored = resolveDescribeErrorDataField(err, 'stored_alt_text');
            const decorative = resolveDescribeErrorDataBooleanField(err, 'is_decorative');
            if (committedAlt !== undefined && stored !== null && decorative !== null) {
              committedAltBaselineRef.current = stored.trim() === '' ? null : stored;
            }
          }
          shouldRestoreFocusRef.current = true;
        },
      },
    ).then(
      // Per-call UI callbacks stop on unmount, but the row may still exist after
      // a draft refetch removes this cell. Hold ownership until the write settles.
      () => onCommitEnd?.(),
      () => onCommitEnd?.(),
    );
  };

  const handleDismiss = (): void => {
    if (isApplyingRef.current || isPending) {
      return;
    }
    reset();
    setDismissed(true);
    onDismiss?.();
  };

  const handleCancelEdit = (): void => {
    if (isApplyingRef.current || isPending) {
      return;
    }
    reset();
    setConflictMessage(null);
    setEditDraft(draftText);
    shouldFocusEditButtonRef.current = true;
    setIsEditing(false);
  };

  return (
    <div
      ref={containerRef}
      className="acx-media-selection__media-alt-suggest"
      role="group"
      aria-busy={isPending ? true : undefined}
      aria-label={isPending ? __('Accepting draft…', 'alt-context') : undefined}
    >
      {isEditing ? (
        <>
          <label htmlFor={textareaId} className="acx-media-selection__media-alt-suggest-edit-label">
            {__('Edit draft alt text', 'alt-context')}
          </label>
          <textarea
            id={textareaId}
            ref={textareaRef}
            className="acx-media-selection__media-alt-suggest-edit-input"
            value={editDraft}
            onChange={(event) => setEditDraft(event.target.value)}
            disabled={isPending}
            aria-invalid={errorMessage ? true : undefined}
            aria-describedby={errorMessage ? errorId : undefined}
          />
        </>
      ) : (
        <p
          className="acx-media-selection__media-alt-draft"
          tabIndex={-1}
          aria-label={draftText.trim() === '' ? __('Empty draft', 'alt-context') : draftText}
        >
          {draftText}
        </p>
      )}
      <p className="acx-media-selection__media-alt-disclosure">
        {__('Drafted by AI — review before saving.', 'alt-context')}
      </p>
      {errorMessage ? (
        <div id={errorId} className="acx-media-selection__media-alt-error" role="alert">
          {errorMessage}
        </div>
      ) : null}
      {isEditing ? (
        <>
          <button
            type="button"
            className="button button-primary acx-media-selection__media-alt-suggest-save"
            onClick={() => applyText(editDraft)}
            disabled={isPending || peerCommitPending || !canSaveEdit}
          >
            {isPending ? __('Saving alt text…', 'alt-context') : __('Save alt text', 'alt-context')}
          </button>
          <button
            type="button"
            className="button button-link acx-media-selection__media-alt-suggest-cancel"
            onClick={handleCancelEdit}
            disabled={isPending}
          >
            {__('Cancel edit', 'alt-context')}
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            ref={acceptButtonRef}
            className="button button-secondary acx-media-selection__media-alt-suggest-accept"
            onClick={() => applyText(draftText)}
            disabled={isPending || peerCommitPending || !canAcceptDraft}
            aria-label={title ? acceptLabel : undefined}
          >
            {isPending ? __('Accepting draft…', 'alt-context') : __('Accept', 'alt-context')}
          </button>
          <button
            type="button"
            ref={editButtonRef}
            className="button acx-media-selection__media-alt-suggest-edit"
            onClick={() => {
              reset();
              setEditDraft(draftText);
              setIsEditing(true);
            }}
            disabled={isPending}
            aria-label={title ? editLabel : undefined}
          >
            {__('Edit draft', 'alt-context')}
          </button>
          <button
            type="button"
            className="button button-link acx-media-selection__media-alt-suggest-dismiss"
            onClick={handleDismiss}
            disabled={isPending}
          >
            {__('Dismiss', 'alt-context')}
          </button>
        </>
      )}
    </div>
  );
};
