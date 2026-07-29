import { __ } from '@wordpress/i18n';
import { useEffect, useId, useRef, useState } from 'react';

import { resolveDescribeErrorMessage } from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';
import { useDescribeMedia } from '../../hooks/useDescribeMedia';
import { useAriaAnnounce } from './identity-clusters/useAriaAnnounce';
import { useFocusPark } from './identity-clusters/useFocusPark';

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
      // BR-46: after the live-region hoist the region is always mounted, so this
      // clear is load-bearing — without it a stale "Generating…" polite cue sits
      // beside the assertive generate-failure alert (same two-regions defect as
      // accept onError clear — BR-39).
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
      // BR-57: land on a control that acts on the draft, not Dismiss (which
      // destroys it). Accept when the draft is committable; otherwise Edit.
      // Dismiss stays in tab order — it is just not the programmatic landing target.
      // No draft-summary fallback: while data is set the non-edit branch always
      // mounts Edit, so editButtonRef is reachable whenever Accept is not.
      if (ownsFocus) {
        if (data.alt_text_draft.trim() !== '') {
          acceptButtonRef.current?.focus();
        } else {
          editButtonRef.current?.focus();
        }
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
  // assertions). Park is instance-scoped (BR-33): only strands that left *this*
  // container are reclaimed — extracted so the host stays within the useEffect
  // budget (BR-44).
  //
  // BR-56: Accept/Save use the same native-disabled blur; park the commit-in-flight
  // window with the same mechanism rather than inventing aria-disabled + click
  // guards. isPending and isAccepting are mutually exclusive on real paths
  // (accept requires data; generate clears edit and only pending is true while
  // describing), so a single park flag is sufficient.
  useFocusPark(isPending || isAccepting, containerRef);

  // BR-17: retire status once it has served its purpose — no timeout. When focus
  // leaves this surface while idle, "Alt text saved." is no longer local context.
  // Review/error/pending keep their messages (still describing this surface).
  const handleContainerBlur = (event: React.FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (next instanceof Node && containerRef.current?.contains(next)) {
      return;
    }
    if (!data && !isPending && !isAccepting && !isError) {
      clearStatus();
    }
  };

  // Named polite live region [A11Y-08]. Always mounted in one stable position
  // outside the branch body (BR-32) so pending → ready → pending only mutates
  // textContent; the AT already tracks the node. Empty while quiet — correct
  // ARIA pattern; announces nothing until text appears.
  //
  // WHY (BR-37): sibling of MediaAltInlineEditor's role=status on the same
  // table row (MediaSelectionTableBody). Distinct data-testid so row-level
  // tests can disambiguate; S2c-4 owns consolidating both into one persistent
  // row-level live region. No key={statusSeq}: a remount on every announce
  // would defeat the stable node.
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
      // BR-38: explicit name + busy on the focus-park target. Without them an
      // unnamed div derives its name from the disabled button text (and, before
      // the live-region hoist, also from the status region) — SR users parked
      // here heard a stuttered or empty label with no in-progress signal.
      // role="group": a role-less div maps to generic, and ARIA 1.2 prohibits
      // an author-supplied name on generic (axe aria-prohibited-attr). group
      // is the in-repo precedent for a labelled composite host (ReviewQueue).
      // Keep native `disabled` on the button (toBeDisabled() / BR-13).
      return (
        <div
          ref={containerRef}
          className="acx-media-selection__media-alt-suggest"
          role="group"
          tabIndex={-1}
          aria-label={__('Generating…', 'alt-context')}
          aria-busy="true"
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
        // BR-56: announce commit-in-flight immediately so the polite region does
        // not keep reading the stale "Draft ready…" cue while the button shows
        // "Accepting draft…".
        announceStatus(__('Accepting draft…', 'alt-context'));
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
            // BR-39: clear polite "Draft ready…" / "Accepting draft…" so it does
            // not co-present with the assertive save-failure alert (same product
            // concern as generate onError clearStatus — BR-46). Empty polite
            // region announces nothing; the role="alert" is the single source of
            // truth for this failure.
            onError: () => {
              clearStatus();
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
        // BR-56 companion: edit-path commit-in-flight cue (mirror Accept).
        announceStatus(__('Saving alt text…', 'alt-context'));
        acceptDraft(
          { mediaId, altText: editDraft },
          {
            onSuccess: () => {
              shouldFocusSuggestRef.current = true;
              announceStatus(__('Alt text saved.', 'alt-context'));
              setIsEditing(false);
              reset();
            },
            // BR-39 companion: edit-path save failure also must not leave a
            // stale polite cue beside the assertive alert.
            onError: () => {
              clearStatus();
            },
          },
        );
      };

      const editDescribedBy = isAcceptError ? `${disclosureId} ${errorId}` : disclosureId;
      const canSaveEdit = editDraft.trim() !== '';
      const canAcceptDraft = data.alt_text_draft.trim() !== '';
      // BR-56: park host mirrors generate. role="group" is constant — not only
      // while accepting — because this node holds programmatically parked focus
      // and a role mutation on park release can destroy/recreate the a11y node
      // (focus-loss). aria-label / aria-busy stay conditional: the idle draft
      // surface has no busy name, and name is already gated so the role need
      // not be. (axe accepts unnamed group; generate host is also unconditional.)
      const acceptingLabel = isEditing ? __('Saving alt text…', 'alt-context') : __('Accepting draft…', 'alt-context');

      return (
        <div
          ref={containerRef}
          className="acx-media-selection__media-alt-suggest"
          role="group"
          tabIndex={-1}
          aria-busy={isAccepting ? true : undefined}
          aria-label={isAccepting ? acceptingLabel : undefined}
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
