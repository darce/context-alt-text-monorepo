import { __ } from '@wordpress/i18n';
import { useEffect, useId, useRef, useState } from 'react';

import { resolveDescribeErrorMessage } from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';
import { useDescribeMedia } from '../../hooks/useDescribeMedia';
import { useAriaAnnounce } from './identity-clusters/useAriaAnnounce';

export interface MediaAltSuggestProps {
  mediaId: number;
}

export const MediaAltSuggest = ({ mediaId }: MediaAltSuggestProps): React.JSX.Element => {
  // House BR-68 pattern (same hook ScanTabContent uses one directory away): seq
  // bumps on every announce so a repeated string (regenerate → same "Draft
  // ready…") still remounts the live region. Plain useState<string> bails out
  // on Object.is-equal sets and aria-live stays silent.
  //
  // In this component the status region is a single always-mounted node
  // (BR-32): branch changes only mutate its textContent. Consecutive equal
  // messages do not occur on any real path here — generate() always inserts
  // "Generating…" between two "Draft ready…" cues — so seq-keyed remount is
  // not load-bearing for MediaAltSuggest. The stable region is.
  const { message: statusMessage, seq: statusSeq, announce: announceStatus } = useAriaAnnounce();
  const [isEditing, setIsEditing] = useState(false);
  const [editDraft, setEditDraft] = useState('');
  const { mutate, isPending, isError, error, data, reset } = useDescribeMedia();
  const {
    mutate: acceptDraft,
    isPending: isAccepting,
    isError: isAcceptError,
    error: acceptError,
    reset: resetAccept,
  } = useCorrectMediaAlt();
  const containerRef = useRef<HTMLDivElement>(null);
  const suggestButtonRef = useRef<HTMLButtonElement>(null);
  const dismissButtonRef = useRef<HTMLButtonElement>(null);
  const retryButtonRef = useRef<HTMLButtonElement>(null);
  const acceptButtonRef = useRef<HTMLButtonElement>(null);
  const saveButtonRef = useRef<HTMLButtonElement>(null);
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const shouldFocusSuggestRef = useRef(false);
  const shouldFocusEditButtonRef = useRef(false);
  const textareaId = useId();
  const disclosureId = useId();
  const errorId = useId();

  // WHY: useAriaAnnounce has no clear; empty string clears the always-mounted
  // region's text without unmounting it (AT keeps tracking the node).
  // Note: this bumps seq on clear (local clear did not).
  const clearStatus = (): void => {
    announceStatus('');
  };

  const generate = (): void => {
    // Announce generating immediately so the pending branch's live region has
    // distinct text from a prior "Draft ready…" (regenerate re-announce path).
    announceStatus(__('Generating…', 'alt-context'));
    resetAccept();
    setIsEditing(false);
    mutate(mediaId, {
      onSuccess: () => {
        announceStatus(__('Draft ready. Review before saving.', 'alt-context'));
      },
      onError: () => {
        clearStatus();
      },
    });
  };

  // When a terminal mutation state mounts (error / draft / idle-after-accept/dismiss),
  // the previously focused control has unmounted — restore focus to an actionable
  // control in the new branch so keyboard/SR users are not stranded on body
  // (WBUX-5-S2C-BR-01). Idle focus only when shouldFocusSuggestRef is set
  // (Dismiss / Accept / Save success), never on the initial mount. Every leg
  // only moves focus when this component still owns it (or focus fell to body) —
  // generation and accept are slow and a per-row control must not yank focus
  // mid-keystroke (WBUX-5-S2C3A-BR-22). shouldFocusSuggestRef is a one-shot
  // intent: clear it on the transition that raised it, even when focus is not
  // granted, so a later re-render cannot fire a stale jump.
  useEffect(() => {
    const active = document.activeElement;
    const ownsFocus = !active || active === document.body || containerRef.current?.contains(active);

    if (isError) {
      if (ownsFocus) {
        retryButtonRef.current?.focus();
      }
    } else if (data) {
      if (ownsFocus) {
        dismissButtonRef.current?.focus();
      }
    } else if (shouldFocusSuggestRef.current) {
      shouldFocusSuggestRef.current = false;
      if (ownsFocus) {
        suggestButtonRef.current?.focus();
      }
    }
  }, [isError, data]);

  // Separate from the draft-landing focus effect: entering edit must not re-key
  // that effect, and Cancel must land on Edit rather than Dismiss.
  useEffect(() => {
    if (isEditing) {
      textareaRef.current?.focus();
    } else if (shouldFocusEditButtonRef.current) {
      shouldFocusEditButtonRef.current = false;
      editButtonRef.current?.focus();
    }
  }, [isEditing]);

  // Accept/Save disable the commit control while isAccepting; the browser blurs
  // it and focus falls to body. On failure the control re-enables but nothing
  // else remounts — put focus back on the button that was pressed
  // (WBUX-5-S2C3A-BR-18). Same ownership gate as draft-landing.
  useEffect(() => {
    if (!isAcceptError) {
      return;
    }
    const active = document.activeElement;
    const ownsFocus = !active || active === document.body || containerRef.current?.contains(active);
    if (!ownsFocus) {
      return;
    }
    if (isEditing) {
      saveButtonRef.current?.focus();
    } else {
      acceptButtonRef.current?.focus();
    }
  }, [isAcceptError, isEditing]);

  // BR-13: native `disabled` on the Generating control blurs focus to body for
  // the whole generation. Keep `disabled` (this repo's toBeDisabled() only
  // honours the HTML attribute, not aria-disabled — measured; switching to
  // aria-disabled alone fails the two existing `.toBeDisabled()` pending
  // assertions). Park focus on the container when focus is stranded on body.
  // Document-level focusout re-checks after the browser's blur-on-disable (and
  // after jsdom stand-ins like parkFocusOnBody) without stealing focus from
  // an operator who has moved elsewhere (activeElement outside + not body).
  useEffect(() => {
    if (!isPending) {
      return;
    }
    const parkIfStranded = (): void => {
      queueMicrotask(() => {
        const node = containerRef.current;
        if (!node) {
          return;
        }
        const active = document.activeElement;
        if (!active || active === document.body) {
          node.focus();
        }
      });
    };
    parkIfStranded();
    document.addEventListener('focusout', parkIfStranded);
    return () => {
      document.removeEventListener('focusout', parkIfStranded);
    };
  }, [isPending]);

  // BR-17: retire status once it has served its purpose — no timeout. When focus
  // leaves this surface while idle, "Alt text saved." is no longer local context.
  // Review/error/pending keep their messages (still describing this surface).
  const handleContainerBlur = (event: React.FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (next instanceof Node && containerRef.current?.contains(next)) {
      return;
    }
    if (!data && !isPending && !isError) {
      clearStatus();
    }
  };

  // Named polite live region [A11Y-08]. Always mounted in one stable position
  // outside the branch body (BR-32) so pending → ready → pending only mutates
  // textContent; the AT already tracks the node. Empty while quiet — correct
  // ARIA pattern; announces nothing until text appears. data-testid disambiguates
  // from MediaAltInlineEditor's sibling role=status on the same table row.
  // No key={statusSeq}: a remount on every announce would defeat the stable node.
  const statusRegion = (
    <div
      role="status"
      aria-live="polite"
      className="screen-reader-text"
      data-testid="media-alt-suggest-status"
      data-announce-seq={statusSeq}
    >
      {statusMessage ?? ''}
    </div>
  );

  const body = (() => {
    if (isPending) {
      return (
        <div
          ref={containerRef}
          className="acx-media-selection__media-alt-suggest"
          tabIndex={-1}
          onBlur={handleContainerBlur}
        >
          <button type="button" className="button acx-media-selection__media-alt-suggest-trigger" disabled>
            {__('Generating…', 'alt-context')}
          </button>
        </div>
      );
    }

    if (isError) {
      return (
        <div
          ref={containerRef}
          className="acx-media-selection__media-alt-suggest"
          tabIndex={-1}
          onBlur={handleContainerBlur}
        >
          <div className="acx-media-selection__media-alt-error" role="alert">
            {resolveDescribeErrorMessage(error, __('Could not generate a draft. Please try again.', 'alt-context'))}
          </div>
          <button
            type="button"
            ref={retryButtonRef}
            className="button acx-media-selection__media-alt-suggest-retry"
            onClick={generate}
          >
            {__('Try again', 'alt-context')}
          </button>
        </div>
      );
    }

    if (data) {
      const accept = (): void => {
        acceptDraft(
          { mediaId, altText: data.alt_text_draft },
          {
            onSuccess: () => {
              shouldFocusSuggestRef.current = true;
              announceStatus(__('Alt text saved.', 'alt-context'));
              // BR-30: setIsEditing(false) removed — Accept only renders in the
              // non-edit branch, so isEditing is already false on every path here.
              reset();
            },
          },
        );
      };

      const enterEditMode = (): void => {
        // Clear sticky correction error so a prior Accept/Save failure does not
        // re-fire as a false alert on a fresh edit attempt (WBUX-5-S2C3A-BR-01).
        resetAccept();
        setEditDraft(data.alt_text_draft);
        setIsEditing(true);
      };

      const cancelEdit = (): void => {
        resetAccept();
        shouldFocusEditButtonRef.current = true;
        setIsEditing(false);
      };

      const saveEdit = (): void => {
        acceptDraft(
          { mediaId, altText: editDraft },
          {
            onSuccess: () => {
              shouldFocusSuggestRef.current = true;
              announceStatus(__('Alt text saved.', 'alt-context'));
              setIsEditing(false);
              reset();
            },
          },
        );
      };

      const editDescribedBy = isAcceptError ? `${disclosureId} ${errorId}` : disclosureId;
      const canSaveEdit = editDraft.trim() !== '';
      const canAcceptDraft = data.alt_text_draft.trim() !== '';

      return (
        <div
          ref={containerRef}
          className="acx-media-selection__media-alt-suggest"
          tabIndex={-1}
          onBlur={handleContainerBlur}
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
                disabled={isAccepting}
                aria-describedby={editDescribedBy}
                aria-invalid={isAcceptError || undefined}
              />
            </>
          ) : (
            <p className="acx-media-selection__media-alt-draft">{data.alt_text_draft}</p>
          )}
          <p id={disclosureId} className="acx-media-selection__media-alt-disclosure">
            {__('Drafted by AI — review before saving.', 'alt-context')}
          </p>
          {isAcceptError ? (
            <div id={errorId} className="acx-media-selection__media-alt-error" role="alert">
              {resolveDescribeErrorMessage(
                acceptError,
                __('Could not save the alt text. Please try again.', 'alt-context'),
              )}
            </div>
          ) : null}
          {isEditing ? (
            <>
              <button
                type="button"
                ref={saveButtonRef}
                className="button button-primary acx-media-selection__media-alt-suggest-save"
                onClick={saveEdit}
                disabled={isAccepting || !canSaveEdit}
              >
                {isAccepting ? __('Saving alt text…', 'alt-context') : __('Save alt text', 'alt-context')}
              </button>
              <button
                type="button"
                className="button button-link acx-media-selection__media-alt-suggest-cancel"
                onClick={cancelEdit}
                disabled={isAccepting}
              >
                {__('Cancel edit', 'alt-context')}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                ref={acceptButtonRef}
                className="button button-primary acx-media-selection__media-alt-suggest-accept"
                onClick={accept}
                disabled={isAccepting || !canAcceptDraft}
                aria-describedby={isAcceptError ? errorId : undefined}
              >
                {isAccepting ? __('Accepting draft…', 'alt-context') : __('Accept', 'alt-context')}
              </button>
              <button
                type="button"
                ref={editButtonRef}
                className="button acx-media-selection__media-alt-suggest-edit"
                onClick={enterEditMode}
                disabled={isAccepting}
              >
                {__('Edit draft', 'alt-context')}
              </button>
              <button
                type="button"
                className="button acx-media-selection__media-alt-suggest-regenerate"
                onClick={generate}
                disabled={isAccepting}
              >
                {__('Regenerate', 'alt-context')}
              </button>
              <button
                type="button"
                ref={dismissButtonRef}
                className="button button-link acx-media-selection__media-alt-suggest-dismiss"
                onClick={() => {
                  shouldFocusSuggestRef.current = true;
                  reset();
                  resetAccept();
                  clearStatus();
                  setIsEditing(false);
                }}
                disabled={isAccepting}
              >
                {__('Dismiss', 'alt-context')}
              </button>
            </>
          )}
        </div>
      );
    }

    return (
      <div
        ref={containerRef}
        className="acx-media-selection__media-alt-suggest"
        tabIndex={-1}
        onBlur={handleContainerBlur}
      >
        <button
          type="button"
          ref={suggestButtonRef}
          className="button acx-media-selection__media-alt-suggest-trigger"
          onClick={generate}
        >
          {__('Suggest alt text', 'alt-context')}
        </button>
      </div>
    );
  })();

  return (
    <>
      {statusRegion}
      {body}
    </>
  );
};
