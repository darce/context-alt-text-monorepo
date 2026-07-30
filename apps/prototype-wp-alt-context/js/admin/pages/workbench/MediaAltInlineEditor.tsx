import { __ } from '@wordpress/i18n';
import { useEffect, useId, useRef, useState } from 'react';

import { resolveDescribeErrorMessage } from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';
import { decodeHtmlEntities } from '../../utils/decodeHtmlEntities';

export interface MediaAltInlineEditorProps {
  mediaId: number;
  altText: string | null;
  /**
   * When provided (row co-mount via MediaSelectionTableBody), polite cues go
   * through the row's single live region and the local status node is omitted.
   * Isolated renders keep a local always-mounted region for component tests.
   */
  onPoliteAnnounce?: (message: string) => void;
  /** Compare-and-clear is enforced by the row owner; this just requests clear. */
  onPoliteClear?: () => void;
}

/** Stored meta arrives entity-encoded; decode once at the read boundary (BR-140). */
const decodeStoredAlt = (stored: string | null): string | null =>
  stored === null ? null : decodeHtmlEntities(stored);

export const MediaAltInlineEditor = ({
  mediaId,
  altText,
  onPoliteAnnounce,
  onPoliteClear,
}: MediaAltInlineEditorProps): React.JSX.Element => {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(() => decodeStoredAlt(altText) ?? '');
  const [displayAlt, setDisplayAlt] = useState<string | null>(() => decodeStoredAlt(altText));
  const [statusMessage, setStatusMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const editButtonRef = useRef<HTMLButtonElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const shouldFocusEditButtonRef = useRef(false);
  const textareaId = useId();
  // Track the raw prop (pre-decode) so a genuine parent refetch is detected even
  // when two distinct stored forms would decode to the same display string.
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
    setDraft(displayAlt ?? '');
    setIsEditing(true);
  };

  const handleCancel = (): void => {
    reset();
    setDraft(displayAlt ?? '');
    shouldFocusEditButtonRef.current = true;
    setIsEditing(false);
  };

  const handleSave = (): void => {
    mutate(
      { mediaId, altText: draft },
      {
        onSuccess: (data) => {
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
      },
    );
  };

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
              disabled={isPending}
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
          {error ? (
            <div className="acx-media-selection__media-alt-error" role="alert">
              {resolveDescribeErrorMessage(error, __('Could not save the alt text. Please try again.', 'alt-context'))}
            </div>
          ) : null}
        </>
      ) : (
        <>
          <p className="acx-media-selection__media-alt-text">{displayAlt ?? __('No alt text yet', 'alt-context')}</p>
          <button
            type="button"
            ref={editButtonRef}
            className="button button-link acx-media-selection__media-alt-edit"
            onClick={enterEditMode}
          >
            {__('Edit alt text', 'alt-context')}
          </button>
        </>
      )}
      {statusRegion}
    </div>
  );
};
