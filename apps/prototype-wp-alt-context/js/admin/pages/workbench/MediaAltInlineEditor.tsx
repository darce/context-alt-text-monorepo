import { __, sprintf } from '@wordpress/i18n';
import { useEffect, useId, useRef, useState } from 'react';

import {
  DESCRIPTION_CORRECTION_CODE,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataField,
  resolveDescribeErrorMessage,
} from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';
import { decodeHtmlEntities } from '../../utils/decodeHtmlEntities';

export interface MediaAltInlineEditorProps {
  mediaId: number;
  altText: string | null;
  /**
   * Row media title for the edit control's accessible name so AT element
   * lists can tell which image each "Edit alt text" belongs to [A11Y-04].
   */
  title?: string;
  /**
   * True when the row carries the durable decorative marker. Idle label must
   * not read "No alt text yet" for a deliberate decorative mark [A11Y-02].
   */
  isDecorative?: boolean;
  /**
   * When provided (row co-mount via MediaSelectionTableBody), polite cues go
   * through the row's single live region and the local status node is omitted.
   * Isolated renders keep a local always-mounted region for component tests.
   */
  onPoliteAnnounce?: (message: string) => void;
  /** Compare-and-clear is enforced by the row owner; this just requests clear. */
  onPoliteClear?: () => void;
  /**
   * True while the sibling Suggest surface has a correction in flight for this
   * mediaId. Transient — never left true from a clean settled state [rg-003].
   */
  peerCommitPending?: boolean;
  /**
   * Row-owned begin of this surface's correction (in-flight exclusivity).
   * Returns false when the row lock is already held — caller must not write.
   */
  onCommitStart?: () => boolean;
  /** Row-owned end of this surface's correction (success or failure). */
  onCommitEnd?: () => void;
}

/** Assertive copy when a sibling committed while the editor buffer was open. */
export const ALT_COMMIT_CONFLICT_MESSAGE = __(
  'The alt text changed while you were editing. Your draft was kept and not saved. Cancel to review the current text.',
  'alt-context',
);

/**
 * Assertive copy when the row lock claim is refused (peer commit in flight).
 * Distinct from ALT_COMMIT_CONFLICT_MESSAGE — that one means the alt moved
 * underneath the operator; this one means a brief busy peer and a retry will
 * work [WBUX-5-S2C4B-BR-05].
 */
export const ALT_COMMIT_CLAIM_REFUSED_MESSAGE = __(
  'Another save is already in progress for this image. Wait a moment, then try again.',
  'alt-context',
);

/** Stored meta arrives entity-encoded; decode once at the read boundary (BR-140). */
const decodeStoredAlt = (stored: string | null): string | null =>
  stored === null ? null : decodeHtmlEntities(stored);

/** Idle label when the row is deliberately decorative (not "missing alt"). */
export const DECORATIVE_IDLE_LABEL = __(
  'Decorative — screen readers will skip this image',
  'alt-context',
);

export const MediaAltInlineEditor = ({
  mediaId,
  altText,
  title,
  isDecorative = false,
  onPoliteAnnounce,
  onPoliteClear,
  peerCommitPending = false,
  onCommitStart,
  onCommitEnd,
}: MediaAltInlineEditorProps): React.JSX.Element => {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(() => decodeStoredAlt(altText) ?? '');
  const [displayAlt, setDisplayAlt] = useState<string | null>(() => decodeStoredAlt(altText));
  const [statusMessage, setStatusMessage] = useState('');
  // Local assertive conflict (CAS refusal) — not a mutation error; not polite.
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const editButtonRef = useRef<HTMLButtonElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const shouldFocusEditButtonRef = useRef(false);
  const textareaId = useId();
  // Track the raw prop (pre-decode) so a genuine parent refetch is detected even
  // when two distinct stored forms would decode to the same display string.
  // Also the CAS baseline: captured when edit mode opens; compared at save
  // against the live committed prop (WBUX-5-S2C3A-BR-06 / BR-73).
  const previousAltTextRef = useRef(altText);
  const { mutate, isPending, error, reset } = useCorrectMediaAlt();

  const usesRowPolite = onPoliteAnnounce != null;

  const announceStatus = (message: string): void => {
    if (onPoliteAnnounce) {
      onPoliteAnnounce(message);
    } else {
      setStatusMessage(message);
    }
  };

  const clearStatus = (): void => {
    if (onPoliteClear) {
      onPoliteClear();
    } else {
      setStatusMessage('');
    }
  };

  // Sync the read display to a genuine prop change (a parent refetch), never
  // merely because edit mode toggled. While editing, the draft is authoritative:
  // return WITHOUT advancing previousAltTextRef so that if the prop changed
  // mid-edit, exiting edit re-runs this effect and applies the pending value
  // (WBUX-5-S2A-BR-03). The prop-equality guard still prevents a save-exit from
  // clobbering the just-saved value back to the (momentarily stale) prop, because
  // handleSave advances previousAltTextRef to the current prop on success.
  useEffect(() => {
    if (isEditing) {
      return;
    }
    if (previousAltTextRef.current === altText) {
      return;
    }
    previousAltTextRef.current = altText;
    const decoded = decodeStoredAlt(altText);
    setDisplayAlt(decoded);
    setDraft(decoded ?? '');
  }, [altText, isEditing]);

  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [isEditing]);

  useEffect(() => {
    if (!isEditing && shouldFocusEditButtonRef.current && editButtonRef.current) {
      editButtonRef.current.focus();
      shouldFocusEditButtonRef.current = false;
    }
  }, [isEditing]);

  const enterEditMode = (): void => {
    reset();
    clearStatus();
    setConflictMessage(null);
    // Capture the committed value we are editing from — CAS baseline at open
    // (S2c-4b-i). previousAltTextRef already tracks prop for display sync; reuse
    // it rather than inventing a second baseline.
    previousAltTextRef.current = altText;
    setDraft(displayAlt ?? '');
    setIsEditing(true);
  };

  const handleCancel = (): void => {
    reset();
    setConflictMessage(null);
    setDraft(displayAlt ?? '');
    shouldFocusEditButtonRef.current = true;
    setIsEditing(false);
  };

  const handleSave = (): void => {
    // Peer Suggest has a correction in flight — UI disables Save, but refuse
    // here too so a same-tick race cannot dual-write.
    if (peerCommitPending || isPending) {
      return;
    }
    // Compare-and-swap: if the row's committed alt moved since edit opened,
    // refuse the write and keep the operator's buffer (BR-06 / BR-73).
    if (previousAltTextRef.current !== altText) {
      setConflictMessage(ALT_COMMIT_CONFLICT_MESSAGE);
      return;
    }
    // beginCommit is compare-and-set [S2c-4b-ii BR-01]: a refused claim must not
    // proceed to write. Isolated renders omit onCommitStart (always proceed).
    // Clear conflict only AFTER a successful claim — a refusal must not wipe an
    // unread warning [WBUX-5-S2C4B-BR-05][RLSE-05].
    const claimed = onCommitStart?.() ?? true;
    if (!claimed) {
      // Keep a pre-existing message; otherwise surface the distinct busy cue.
      setConflictMessage((prev) => prev ?? ALT_COMMIT_CLAIM_REFUSED_MESSAGE);
      return;
    }
    setConflictMessage(null);
    mutate(
      { mediaId, altText: draft },
      {
        onSuccess: (data) => {
          onCommitEnd?.();
          // current_alt_text is stored meta (entity-encoded); decode for display.
          // Fallback to the operator draft (already plain text) when absent.
          const nextAlt =
            data && typeof data.current_alt_text === 'string'
              ? decodeHtmlEntities(data.current_alt_text)
              : draft;
          // Acknowledge whatever prop value is current at save time so the
          // exit-edit sync effect won't re-apply a mid-edit prop change over the
          // just-saved value (WBUX-5-S2A-BR-03 companion). useCorrectMediaAlt
          // patches the workbench row from the server response; the parent will
          // re-render with that server-truth prop.
          previousAltTextRef.current = altText;
          setDisplayAlt(nextAlt);
          setDraft(nextAlt);
          announceStatus(__('Alt text saved.', 'alt-context'));
          // Return focus to the Edit control like Cancel does; without this the
          // disabled Save button detaches and focus falls to document.body
          // (WBUX-5-S2A-BR-01).
          shouldFocusEditButtonRef.current = true;
          setIsEditing(false);
        },
        onError: (err) => {
          onCommitEnd?.();
          // Re-seed CAS baseline from PARTIAL reconcile so the operator's own
          // half-failed write is not misread as a sibling conflict on retry
          // [rg-002]. Empty stored alt matches class-api.php:346 null.
          if (resolveDescribeErrorCode(err) === DESCRIPTION_CORRECTION_CODE.PARTIAL) {
            const stored = resolveDescribeErrorDataField(err, 'stored_alt_text');
            if (stored !== null) {
              previousAltTextRef.current = stored.trim() === '' ? null : stored;
            }
          }
        },
      },
    );
  };

  const idleAltLabel = displayAlt ?? (isDecorative ? DECORATIVE_IDLE_LABEL : __('No alt text yet', 'alt-context'));

  // BR-58 / Suggest BR-17: retire status once it has served its purpose — no
  // timeout. When focus leaves this surface while idle, "Alt text saved." is no
  // longer local context. Clear goes through ownership when the row owns the
  // region — a stale sibling cannot wipe a Suggest-owned cue.
  const handleContainerBlur = (event: React.FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (next instanceof Node && containerRef.current?.contains(next)) {
      return;
    }
    if (!isEditing && !isPending) {
      clearStatus();
    }
  };

  // Local polite region only when not co-mounted under the row [S2c-4a].
  // Always-mounted, empty while quiet (BR-32 / BR-58).
  const statusRegion = usesRowPolite ? null : (
    <div role="status" aria-live="polite" className="screen-reader-text" data-testid="media-alt-inline-editor-status">
      {statusMessage}
    </div>
  );

  return (
    <div
      ref={containerRef}
      className={isEditing ? 'acx-media-selection__media-alt-editor' : 'acx-media-selection__media-alt'}
      onBlur={handleContainerBlur}
    >
      {isEditing ? (
        <>
          <label htmlFor={textareaId}>{__('Alt text', 'alt-context')}</label>
          <textarea
            id={textareaId}
            ref={textareaRef}
            className="acx-media-selection__media-alt-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            disabled={isPending}
          />
          <div className="acx-media-selection__media-alt-actions">
            <button
              type="button"
              className="button acx-media-selection__media-alt-save"
              onClick={handleSave}
              disabled={isPending || peerCommitPending}
            >
              {isPending ? __('Saving…', 'alt-context') : __('Save', 'alt-context')}
            </button>
            <button
              type="button"
              className="button button-link acx-media-selection__media-alt-cancel"
              onClick={handleCancel}
              disabled={isPending}
            >
              {__('Cancel', 'alt-context')}
            </button>
          </div>
          {conflictMessage ? (
            <div className="acx-media-selection__media-alt-error" role="alert">
              {conflictMessage}
            </div>
          ) : error ? (
            <div className="acx-media-selection__media-alt-error" role="alert">
              {resolveDescribeErrorMessage(error, __('Could not save the alt text. Please try again.', 'alt-context'))}
            </div>
          ) : null}
        </>
      ) : (
        <>
          <p className="acx-media-selection__media-alt-text">{idleAltLabel}</p>
          <button
            type="button"
            ref={editButtonRef}
            className="button button-link acx-media-selection__media-alt-edit"
            onClick={enterEditMode}
            aria-label={
              title
                ? sprintf(__('Edit alt text for %s', 'alt-context'), title)
                : undefined
            }
          >
            {__('Edit alt text', 'alt-context')}
          </button>
        </>
      )}
      {statusRegion}
    </div>
  );
};
