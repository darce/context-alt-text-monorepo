import { __ } from '@wordpress/i18n';
import { useEffect, useId, useRef, useState } from 'react';

import { resolveDescribeErrorMessage } from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';

export interface MediaAltInlineEditorProps {
  mediaId: number;
  altText: string | null;
}

export const MediaAltInlineEditor = ({
  mediaId,
  altText,
}: MediaAltInlineEditorProps): React.JSX.Element => {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(altText ?? '');
  const [displayAlt, setDisplayAlt] = useState<string | null>(altText);
  const [statusMessage, setStatusMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const editButtonRef = useRef<HTMLButtonElement | null>(null);
  const shouldFocusEditButtonRef = useRef(false);
  const textareaId = useId();
  const previousAltTextRef = useRef(altText);
  const { mutate, isPending, error, reset } = useCorrectMediaAlt();

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
    setDisplayAlt(altText);
    setDraft(altText ?? '');
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
    setStatusMessage('');
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
          const nextAlt =
            data && typeof data.current_alt_text === 'string'
              ? data.current_alt_text
              : draft;
          // Acknowledge whatever prop value is current at save time so the
          // exit-edit sync effect won't re-apply a mid-edit prop change over the
          // just-saved value (WBUX-5-S2A-BR-03 companion). The mandatory media
          // query invalidation will land the server-truth prop shortly after.
          previousAltTextRef.current = altText;
          setDisplayAlt(nextAlt);
          setDraft(nextAlt);
          setStatusMessage(__('Alt text saved.', 'alt-context'));
          // Return focus to the Edit control like Cancel does; without this the
          // disabled Save button detaches and focus falls to document.body
          // (WBUX-5-S2A-BR-01).
          shouldFocusEditButtonRef.current = true;
          setIsEditing(false);
        },
      },
    );
  };

  if (isEditing) {
    return (
      <div className="acx-media-selection__media-alt-editor">
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
            {resolveDescribeErrorMessage(
              error,
              __('Could not save the alt text. Please try again.', 'alt-context'),
            )}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="acx-media-selection__media-alt">
      <p className="acx-media-selection__media-alt-text">
        {displayAlt ?? __('No alt text yet', 'alt-context')}
      </p>
      <button
        type="button"
        ref={editButtonRef}
        className="button button-link acx-media-selection__media-alt-edit"
        onClick={enterEditMode}
      >
        {__('Edit alt text', 'alt-context')}
      </button>
      {/* WHY (BR-37): sibling of MediaAltSuggest's role=status on the same table
          row (MediaSelectionTableBody). Distinct data-testid so row-level tests
          can disambiguate; S2c-4 owns consolidating both into one persistent
          row-level live region. Mount-with-text still present here — out of
          scope for this stopgap. */}
      {statusMessage ? (
        <div
          role="status"
          aria-live="polite"
          className="screen-reader-text"
          data-testid="media-alt-inline-editor-status"
        >
          {statusMessage}
        </div>
      ) : null}
    </div>
  );
};