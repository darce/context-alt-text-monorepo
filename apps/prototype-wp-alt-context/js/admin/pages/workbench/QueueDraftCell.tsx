import { __, sprintf } from '@wordpress/i18n';
import { useEffect, useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { resolveDescribeErrorMessage } from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';
import { QUEUE_DRAFTS_HISTORY_QUERY_KEY } from '../../hooks/useQueueDrafts';

export interface QueueDraftCellProps {
  mediaId: number;
  draftText: string;
  title?: string;
  onDismiss?: () => void;
  onApplied?: () => void;
}

const APPLY_ERROR_FALLBACK = __('Could not save the alt text. Please try again.', 'alt-context');
const DESCRIBE_RUN_ITEMS_QUERY_PREFIX = ['describe-run-items'] as const;

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
}: QueueDraftCellProps): React.JSX.Element | null => {
  const [isEditing, setIsEditing] = useState(false);
  const [editDraft, setEditDraft] = useState(draftText);
  const [dismissed, setDismissed] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const acceptButtonRef = useRef<HTMLButtonElement | null>(null);
  const editButtonRef = useRef<HTMLButtonElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const shouldFocusEditButtonRef = useRef(false);
  const textareaId = useId();
  const errorId = useId();
  const queryClient = useQueryClient();
  const { mutate, isPending, error, reset } = useCorrectMediaAlt();

  const canAcceptDraft = draftText.trim() !== '';
  const canSaveEdit = editDraft.trim() !== '';
  const acceptLabel = title ? sprintf(__('Accept draft for %s', 'alt-context'), title) : __('Accept', 'alt-context');
  const editLabel = title ? sprintf(__('Edit draft for %s', 'alt-context'), title) : __('Edit draft', 'alt-context');

  useEffect(() => {
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
  }, [canAcceptDraft]);

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

  if (dismissed) {
    return null;
  }

  const applyText = (altText: string): void => {
    if (isPending || altText.trim() === '') {
      return;
    }
    mutate(
      { mediaId, altText },
      {
        onSuccess: () => {
          void queryClient.invalidateQueries({ queryKey: DESCRIBE_RUN_ITEMS_QUERY_PREFIX });
          void queryClient.invalidateQueries({ queryKey: QUEUE_DRAFTS_HISTORY_QUERY_KEY });
          onApplied?.();
          setDismissed(true);
        },
      },
    );
  };

  const handleDismiss = (): void => {
    if (isPending) {
      return;
    }
    reset();
    setDismissed(true);
    onDismiss?.();
  };

  const handleCancelEdit = (): void => {
    if (isPending) {
      return;
    }
    reset();
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
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
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
      {error ? (
        <div id={errorId} className="acx-media-selection__media-alt-error" role="alert">
          {resolveDescribeErrorMessage(error, APPLY_ERROR_FALLBACK)}
        </div>
      ) : null}
      {isEditing ? (
        <>
          <button
            type="button"
            className="button button-primary acx-media-selection__media-alt-suggest-save"
            onClick={() => applyText(editDraft)}
            disabled={isPending || !canSaveEdit}
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
            disabled={isPending || !canAcceptDraft}
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
