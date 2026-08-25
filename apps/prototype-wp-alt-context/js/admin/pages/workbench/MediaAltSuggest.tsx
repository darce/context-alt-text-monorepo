import { __, sprintf } from '@wordpress/i18n';
import { useEffect, useId, useRef, useState } from 'react';

import {
  DESCRIPTION_CORRECTION_CODE,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataField,
  resolveDescribeErrorMessage,
} from '../../api/describeApi';
import { useCorrectMediaAlt } from '../../hooks/useCorrectMediaAlt';
import { useDescribeMedia } from '../../hooks/useDescribeMedia';
import { useAriaAnnounce } from './identity-clusters/useAriaAnnounce';
import { useFocusPark } from './identity-clusters/useFocusPark';

/**
 * Recommended maximum length for alt text, in characters.
 *
 * Source: practical convention from screen-reader guidance (commonly cited ~125
 * characters so the full description can be heard without excessive verbosity).
 * This figure is advisory only — WCAG does not specify a maximum alt-text length,
 * and this constant must not be described as a normative WCAG limit in UI copy.
 *
 * Boundary: exclusive over — length > RECOMMENDED_ALT_TEXT_MAX_LENGTH is over;
 * length equal to the constant is still within the recommendation.
 */
export const RECOMMENDED_ALT_TEXT_MAX_LENGTH = 125;

export interface MediaAltSuggestProps {
  mediaId: number;
  /**
   * The row's current committed alt text (live after any surface's successful
   * correction). Required for compare-and-swap at Accept/Save — without it
   * Suggest cannot observe a sibling commit (WBUX-5-S2C3A-BR-06 / BR-73).
   * Optional only so isolated unit tests can omit it; defaults to null.
   */
  committedAlt?: string | null;
  /**
   * Whether the row already holds the durable decorative marker. Required —
   * no silent default — so the control can offer the inverse operation when
   * marked [A-02][INT-09]. A silent default is how A-03 went wrong.
   */
  isDecorative: boolean;
  /**
   * Row media title for Suggest / Mark decorative accessible names so AT
   * element lists can tell which image each bare verb belongs to [A11Y-04].
   * When absent, controls keep their short visible labels as accessible names.
   */
  title?: string;
  /**
   * When provided (row co-mount via MediaSelectionTableBody), polite cues go
   * through the row's single live region and the local status node is omitted.
   * Isolated renders keep a local always-mounted region for component tests.
   */
  onPoliteAnnounce?: (message: string) => void;
  /** Compare-and-clear is enforced by the row owner; this just requests clear. */
  onPoliteClear?: () => void;
  /**
   * True while the sibling inline editor has a correction in flight for this
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

/** Assertive copy when a sibling committed while a Suggest draft was sticky. */
export const ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE = __(
  'The alt text changed while you were reviewing this draft. Your draft was kept and not saved. Dismiss to clear the draft, or keep it.',
  'alt-context',
);

/**
 * Assertive copy when the row lock claim is refused (peer commit in flight).
 * Distinct from ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE — that one means the alt
 * moved underneath the operator; this one means a brief busy peer and a retry
 * will work [WBUX-5-S2C4B-BR-05].
 */
export const ALT_SUGGEST_COMMIT_CLAIM_REFUSED_MESSAGE = __(
  'Another save is already in progress for this image. Wait a moment, then try again.',
  'alt-context',
);

/**
 * Explicit control to mark the image decorative (empty alt + durable marker).
 * Label states the screen-reader outcome — "decorative" alone is jargon [INT-06]
 * [A11Y-02]. Recoverable: un-mark control when isDecorative, or a later
 * non-empty description clears the marker server-side [INT-09].
 */
export const MARK_DECORATIVE_LABEL = __(
  'Mark as decorative — screen readers will announce nothing',
  'alt-context',
);

/** Polite success after a deliberate decorative mark. Mentions undo path. */
export const MARK_DECORATIVE_SUCCESS_MESSAGE = __(
  'Marked as decorative. Screen readers will skip this image. You can remove the decorative mark later to undo.',
  'alt-context',
);

/**
 * Inverse of MARK_DECORATIVE_LABEL when the row is already marked [INT-06][INT-09].
 * Names the operation (remove decorative mark) and the destination (to-do list)
 * so the two control states are distinguishable and the operator knows where
 * the image goes after undo.
 */
export const UNMARK_DECORATIVE_LABEL = __(
  'Remove decorative mark — return image to the to-do list',
  'alt-context',
);

/** Polite success after un-mark: tells the operator the image is back on the missing list. */
export const UNMARK_DECORATIVE_SUCCESS_MESSAGE = __(
  'Decorative mark removed. The image is back on the missing-alt to-do list.',
  'alt-context',
);

/** True when the commit-candidate string exceeds the recommended maximum. */
export const isOverRecommendedAltLength = (altText: string): boolean =>
  altText.length > RECOMMENDED_ALT_TEXT_MAX_LENGTH;

/** Visible advisory copy: names actual length, threshold, and what to do. */
export const formatAltLengthAdvisory = (length: number): string =>
  sprintf(
    /* translators: 1: actual character count of the draft; 2: recommended maximum characters */
    __(
      'This draft is %1$d characters. The recommended maximum is %2$d characters so screen readers can convey the description without excessive length. Consider shortening it before saving.',
      'alt-context',
    ),
    length,
    RECOMMENDED_ALT_TEXT_MAX_LENGTH,
  );

/** Polite-status composition when a generated draft lands over the recommendation. */
export const formatOverLengthReadyAnnouncement = (length: number): string =>
  sprintf(
    /* translators: 1: actual character count of the draft; 2: recommended maximum characters */
    __(
      'Draft ready. Review before saving. This draft is %1$d characters; recommended maximum is %2$d. Consider shortening it.',
      'alt-context',
    ),
    length,
    RECOMMENDED_ALT_TEXT_MAX_LENGTH,
  );

/** Polite cue when a draft crosses back under the recommended maximum while editing. */
export const formatWithinLengthAnnouncement = (): string =>
  __('Draft is within the recommended maximum length.', 'alt-context');

export const MediaAltSuggest = ({
  mediaId,
  committedAlt = null,
  isDecorative,
  title,
  onPoliteAnnounce,
  onPoliteClear,
  peerCommitPending = false,
  onCommitStart,
  onCommitEnd,
}: MediaAltSuggestProps): React.JSX.Element => {
  // Row-qualified accessible names when title is known; bare verbs otherwise
  // so isolated tests and title-less rows stay labelled [A11Y-04][B-03].
  const suggestTriggerLabel = title
    ? sprintf(__('Suggest alt text for %s', 'alt-context'), title)
    : undefined;
  // Distinct label per state so AT users do not act on the wrong operation [INT-06].
  const decorativeControlAriaLabel = title
    ? isDecorative
      ? sprintf(__('Remove decorative mark for %s', 'alt-context'), title)
      : sprintf(__('Mark as decorative for %s', 'alt-context'), title)
    : undefined;
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
  //
  // When co-mounted under MediaSelectionTableBody (S2c-4a), polite cues go
  // through onPoliteAnnounce / onPoliteClear and the local region is omitted.
  const {
    message: localStatusMessage,
    seq: statusSeq,
    announce: localAnnounceStatus,
  } = useAriaAnnounce();
  const usesRowPolite = onPoliteAnnounce != null;
  const announceStatus = (message: string): void => {
    if (onPoliteAnnounce) {
      onPoliteAnnounce(message);
    } else {
      localAnnounceStatus(message);
    }
  };
  const [isEditing, setIsEditing] = useState(false);
  const [editDraft, setEditDraft] = useState('');
  // Local assertive conflict (CAS refusal) — not a mutation error; not polite.
  // Also used for decorative-mark failures (same assertive channel; no new region).
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);
  // Decorative commits go through useCorrectMediaAlt (decorative:true) so
  // onSuccess / PARTIAL onError still patch the workbench cache [S7-BR-01]
  // [S7-BR-02]. Local flag only drives "Marking as decorative…" labels while
  // isAccepting covers the shared in-flight disable + focus park [BR-13][BR-56].
  const [isMarkingDecorative, setIsMarkingDecorative] = useState(false);
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
  const decorativeButtonRef = useRef<HTMLButtonElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const shouldFocusSuggestRef = useRef(false);
  const shouldFocusEditButtonRef = useRef(false);
  // Previous over/under side for one-shot length-crossing announcements
  // [WBUX-5-S2C4A-BR-01]. Seeded on generate success and when entering edit.
  const wasOverLengthRef = useRef(false);
  // CAS baseline: committed alt at draft-generate (and re-captured on edit-draft
  // open). Compared at Accept/Save against the live committedAlt prop.
  const committedAltBaselineRef = useRef<string | null>(committedAlt);
  // Live committed prop mirror so generate onSuccess (async) captures the value
  // at draft-arrival, not a stale closure from the click render. Written in an
  // effect — never during render [S2c-4b-ii BR-02 / React ref rules].
  const committedAltRef = useRef<string | null>(committedAlt);
  useEffect(() => {
    committedAltRef.current = committedAlt;
  }, [committedAlt]);
  // Synchronous in-flight guard for Accept/Save [S2C3A-BR-16]. isAccepting
  // only paints after the next render; a same-tick double activation must not
  // enqueue two corrections. Mirror of DescriptionHistoryPage BR-81.
  const isAcceptingRef = useRef(false);
  // Which surface owned the last correction — survives isMarkingDecorative
  // clearing in onError so the isAcceptError focus-restore lands on the
  // control that failed, not Accept [S6-A-05][A11Y-11].
  const lastCorrectionWasDecorativeRef = useRef(false);
  // Click-time mark/un-mark direction for busy labels. isDecorative can flip
  // mid-flight (cache patch / parent re-render); live prop would invert the
  // AT-facing busy name [A11Y-02]. Same capture discipline as announceStatus.
  const decorativeBusyUnmarkingRef = useRef(false);
  const textareaId = useId();
  const disclosureId = useId();
  const errorId = useId();
  const lengthAdvisoryId = useId();

  // WHY: useAriaAnnounce has no clear; empty string clears the always-mounted
  // region's text without unmounting it (AT keeps tracking the node).
  // Note: this bumps seq on clear (local clear did not).
  // Row co-mount: clear requests go through ownership check at the row.
  const clearStatus = (): void => {
    if (onPoliteClear) {
      onPoliteClear();
    } else {
      announceStatus('');
    }
  };

  const generate = (): void => {
    // Announce generating immediately so the pending branch's live region has
    // distinct text from a prior "Draft ready…" (regenerate re-announce path).
    announceStatus(__('Generating…', 'alt-context'));
    resetAccept();
    setConflictMessage(null);
    setIsEditing(false);
    mutate(mediaId, {
      onSuccess: (response) => {
        // Capture the committed alt we are working from at draft generation
        // (CAS baseline). Re-captured again when edit-draft mode opens.
        committedAltBaselineRef.current = committedAltRef.current;
        // [A11Y-34] branch (c): when the generated draft exceeds the recommended
        // maximum, announce the length check once via the existing polite region
        // (composed with the ready cue). Do not add a second live region [A11Y-19].
        const draftText = response.alt_text_draft;
        const isOver = isOverRecommendedAltLength(draftText);
        wasOverLengthRef.current = isOver;
        if (isOver) {
          announceStatus(formatOverLengthReadyAnnouncement(draftText.length));
        } else {
          announceStatus(__('Draft ready. Review before saving.', 'alt-context'));
        }
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

  /**
   * One-shot length-crossing announcement while editing [WBUX-5-S2C4A-BR-01].
   * Visible advisory stays keystroke-live; only the polite cue is crossing-gated.
   */
  const handleEditDraftChange = (next: string): void => {
    const wasOver = wasOverLengthRef.current;
    const isOver = isOverRecommendedAltLength(next);
    setEditDraft(next);
    if (isOver && !wasOver) {
      announceStatus(formatAltLengthAdvisory(next.length));
    } else if (!isOver && wasOver) {
      announceStatus(formatWithinLengthAnnouncement());
    }
    wasOverLengthRef.current = isOver;
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

  // Accept/Save/decorative disable the commit control while in flight; the
  // browser blurs it and focus falls to body. On failure the control re-enables
  // but nothing else remounts — put focus back on the button that was pressed
  // (WBUX-5-S2C3A-BR-18). Decorative shares the mutation so isAcceptError fires
  // for it too; lastCorrectionWasDecorativeRef picks the landing target
  // [S6-A-05]. Same ownership gate as draft-landing.
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
    } else if (lastCorrectionWasDecorativeRef.current) {
      decorativeButtonRef.current?.focus();
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
  // describing), so a single park flag is sufficient. isMarkingDecorative is a
  // third exclusive commit path (direct correction with decorative:true) and
  // joins the same park window for the same blur reason.
  const isCommitInFlight = isAccepting || isMarkingDecorative;
  useFocusPark(isPending || isCommitInFlight, containerRef);

  /**
   * Deliberate decorative mark or un-mark [A-02][INT-09].
   * Mark: empty alt + decorative:true. Un-mark: decorative:false with the
   * currently committed alt preserved (clear the marker, not the description).
   * Separate from Accept/Save so clearing the box cannot silently mark
   * decorative [WBUX-5-S2C3C-BR-01]. Routes through useCorrectMediaAlt so the
   * shared onSuccess patch (patchWorkbenchRowAlt + invalidateMediaStats) and
   * PARTIAL onError stored_alt_text reconcile still run [S7-BR-01][S7-BR-02]
   * [HARM-BR-02].
   */
  const toggleDecorative = (): void => {
    if (isAcceptingRef.current || isAccepting || isMarkingDecorative || peerCommitPending) {
      return;
    }
    // CAS when a draft session captured a baseline (draft / edit surfaces).
    if (data && committedAltBaselineRef.current !== committedAlt) {
      setConflictMessage(ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE);
      return;
    }
    // Claim before clear — same RLSE-05 discipline as Accept/Save [WBUX-5-S2C4B-BR-05].
    const claimed = onCommitStart?.() ?? true;
    if (!claimed) {
      setConflictMessage((prev) => prev ?? ALT_SUGGEST_COMMIT_CLAIM_REFUSED_MESSAGE);
      return;
    }
    // Capture direction at click: isDecorative may flip after cache patch.
    const unmarking = isDecorative;
    setConflictMessage(null);
    isAcceptingRef.current = true;
    decorativeBusyUnmarkingRef.current = unmarking;
    setIsMarkingDecorative(true);
    lastCorrectionWasDecorativeRef.current = true;
    announceStatus(
      unmarking
        ? __('Removing decorative mark…', 'alt-context')
        : __('Marking as decorative…', 'alt-context'),
    );
    // Same correction mutation as Accept/Save — decorative flag is additive.
    // Hook onSuccess patches cache from data.current_alt_text; hook onError
    // reconciles PARTIAL from stored_alt_text. Local callbacks only own UI.
    // Un-mark clears the marker only — preserve committed alt (null → '').
    // Mark still blanks alt (decorative requires empty). Live prop, not ref:
    // CAS above already compared against this render's committedAlt, and this
    // arm is sync at click (ref is for async draft-arrival capture).
    acceptDraft(
      {
        mediaId,
        altText: unmarking ? (committedAlt ?? '') : '',
        decorative: unmarking ? false : true,
      },
      {
        onSuccess: () => {
          isAcceptingRef.current = false;
          setIsMarkingDecorative(false);
          onCommitEnd?.();
          shouldFocusSuggestRef.current = true;
          announceStatus(
            unmarking ? UNMARK_DECORATIVE_SUCCESS_MESSAGE : MARK_DECORATIVE_SUCCESS_MESSAGE,
          );
          setIsEditing(false);
          setConflictMessage(null);
          reset();
        },
        onError: (err) => {
          isAcceptingRef.current = false;
          setIsMarkingDecorative(false);
          onCommitEnd?.();
          clearStatus();
          // Re-seed CAS baseline from PARTIAL reconcile so the operator's own
          // half-failed write is not misread as a sibling conflict on retry
          // [rg-002][S6-A-02]. Empty stored alt matches class-api.php:346 null.
          if (resolveDescribeErrorCode(err) === DESCRIPTION_CORRECTION_CODE.PARTIAL) {
            const stored = resolveDescribeErrorDataField(err, 'stored_alt_text');
            if (stored !== null) {
              committedAltBaselineRef.current = stored.trim() === '' ? null : stored;
            }
          }
          // Assertive channel via existing conflictMessage region — no new live region
          // [A11Y-21]. Prefer server message (400 contradiction / PARTIAL) when structured.
          setConflictMessage(
            resolveDescribeErrorMessage(
              err,
              unmarking
                ? __('Could not remove decorative mark. Please try again.', 'alt-context')
                : __('Could not mark as decorative. Please try again.', 'alt-context'),
            ),
          );
        },
      },
    );
  };

  // BR-17: retire status once it has served its purpose — no timeout. When focus
  // leaves this surface while idle, "Alt text saved." is no longer local context.
  // Review/error/pending keep their messages (still describing this surface).
  const handleContainerBlur = (event: React.FocusEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (next instanceof Node && containerRef.current?.contains(next)) {
      return;
    }
    if (!data && !isPending && !isAccepting && !isMarkingDecorative && !isError) {
      clearStatus();
    }
  };

  // Local polite region only when not co-mounted under the row [S2c-4a].
  // Always mounted in one stable position outside the branch body (BR-32).
  // No key={statusSeq}: a remount on every announce would defeat the stable node.
  const statusRegion = usesRowPolite ? null : (
    <div
      role="status"
      aria-live="polite"
      className="screen-reader-text"
      data-testid="media-alt-suggest-status"
      data-announce-seq={statusSeq}
    >
      {localStatusMessage ?? ''}
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
        // Ref guard first — isAccepting only disables after the next paint
        // [S2C3A-BR-16]. Same defect class as DescriptionHistoryPage BR-81.
        if (isAcceptingRef.current || isAccepting || peerCommitPending) {
          return;
        }
        // Compare-and-swap against the committed alt captured at generate
        // (or edit-draft open). If a sibling committed, refuse and keep draft.
        if (committedAltBaselineRef.current !== committedAlt) {
          setConflictMessage(ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE);
          return;
        }
        // beginCommit is compare-and-set [S2c-4b-ii BR-01]: a refused claim must
        // not proceed to write. Isolated renders omit onCommitStart (proceed).
        // Clear conflict only AFTER a successful claim — a refusal must not wipe
        // an unread warning [WBUX-5-S2C4B-BR-05][RLSE-05].
        const claimed = onCommitStart?.() ?? true;
        if (!claimed) {
          // Keep a pre-existing message; otherwise surface the distinct busy cue.
          setConflictMessage((prev) => prev ?? ALT_SUGGEST_COMMIT_CLAIM_REFUSED_MESSAGE);
          return;
        }
        setConflictMessage(null);
        isAcceptingRef.current = true;
        lastCorrectionWasDecorativeRef.current = false;
        // BR-56: announce commit-in-flight immediately so the polite region does
        // not keep reading the stale "Draft ready…" cue while the button shows
        // "Accepting draft…".
        announceStatus(__('Accepting draft…', 'alt-context'));
        acceptDraft(
          { mediaId, altText: data.alt_text_draft },
          {
            onSuccess: () => {
              isAcceptingRef.current = false;
              onCommitEnd?.();
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
            onError: (err) => {
              isAcceptingRef.current = false;
              onCommitEnd?.();
              clearStatus();
              // Own PARTIAL write moved the cache — re-seed so Accept retry is not CAS-blocked.
              if (resolveDescribeErrorCode(err) === DESCRIPTION_CORRECTION_CODE.PARTIAL) {
                const stored = resolveDescribeErrorDataField(err, 'stored_alt_text');
                if (stored !== null) {
                  committedAltBaselineRef.current = stored.trim() === '' ? null : stored;
                }
              }
            },
          },
        );
      };

      const enterEditMode = (): void => {
        // Clear sticky correction error so a prior Accept/Save failure does not
        // re-fire as a false alert on a fresh edit attempt (WBUX-5-S2C3A-BR-01).
        resetAccept();
        setConflictMessage(null);
        // Re-capture CAS baseline when edit-draft mode opens.
        committedAltBaselineRef.current = committedAlt;
        setEditDraft(data.alt_text_draft);
        // Seed crossing side so entering edit on an already-over draft does not
        // re-announce; only a true under→over or over→under edge fires.
        wasOverLengthRef.current = isOverRecommendedAltLength(data.alt_text_draft);
        setIsEditing(true);
      };

      const cancelEdit = (): void => {
        resetAccept();
        setConflictMessage(null);
        shouldFocusEditButtonRef.current = true;
        setIsEditing(false);
      };

      const saveEdit = (): void => {
        if (isAcceptingRef.current || isAccepting || peerCommitPending) {
          return;
        }
        if (committedAltBaselineRef.current !== committedAlt) {
          setConflictMessage(ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE);
          return;
        }
        // Claim before clear — same RLSE-05 discipline as Accept [WBUX-5-S2C4B-BR-05].
        const claimed = onCommitStart?.() ?? true;
        if (!claimed) {
          setConflictMessage((prev) => prev ?? ALT_SUGGEST_COMMIT_CLAIM_REFUSED_MESSAGE);
          return;
        }
        setConflictMessage(null);
        isAcceptingRef.current = true;
        lastCorrectionWasDecorativeRef.current = false;
        // BR-56 companion: edit-path commit-in-flight cue (mirror Accept).
        announceStatus(__('Saving alt text…', 'alt-context'));
        acceptDraft(
          { mediaId, altText: editDraft },
          {
            onSuccess: () => {
              isAcceptingRef.current = false;
              onCommitEnd?.();
              shouldFocusSuggestRef.current = true;
              announceStatus(__('Alt text saved.', 'alt-context'));
              setIsEditing(false);
              reset();
            },
            // BR-39 companion: edit-path save failure also must not leave a
            // stale polite cue beside the assertive alert.
            onError: (err) => {
              isAcceptingRef.current = false;
              onCommitEnd?.();
              clearStatus();
              // Own PARTIAL write moved the cache — re-seed so Save retry is not CAS-blocked.
              if (resolveDescribeErrorCode(err) === DESCRIPTION_CORRECTION_CODE.PARTIAL) {
                const stored = resolveDescribeErrorDataField(err, 'stored_alt_text');
                if (stored !== null) {
                  committedAltBaselineRef.current = stored.trim() === '' ? null : stored;
                }
              }
            },
          },
        );
      };

      // Assess the string the author would actually commit — re-evaluates live as
      // they type in edit mode (editDraft) or from the generated draft otherwise.
      const commitCandidate = isEditing ? editDraft : data.alt_text_draft;
      const isOverLength = isOverRecommendedAltLength(commitCandidate);
      const showCommitError = conflictMessage != null || isAcceptError;
      // Extend editDescribedBy composition; do not replace. Keep error id when set.
      const editDescribedBy = [
        disclosureId,
        ...(isOverLength ? [lengthAdvisoryId] : []),
        ...(showCommitError ? [errorId] : []),
      ].join(' ');
      const canSaveEdit = editDraft.trim() !== '';
      const canAcceptDraft = data.alt_text_draft.trim() !== '';
      // Non-empty gates stay on Accept/Save only — decorative is a separate
      // deliberate action and must not ride those gates [WBUX-5-S2C3C-BR-01].
      const commitControlDisabled = isCommitInFlight || peerCommitPending;
      // BR-56: park host mirrors generate. role="group" is constant — not only
      // while accepting — because this node holds programmatically parked focus
      // and a role mutation on park release can destroy/recreate the a11y node
      // (focus-loss). aria-label / aria-busy stay conditional: the idle draft
      // surface has no busy name, and name is already gated so the role need
      // not be. (axe accepts unnamed group; generate host is also unconditional.)
      const acceptingLabel = isMarkingDecorative
        ? decorativeBusyUnmarkingRef.current
          ? __('Removing decorative mark…', 'alt-context')
          : __('Marking as decorative…', 'alt-context')
        : isEditing
          ? __('Saving alt text…', 'alt-context')
          : __('Accepting draft…', 'alt-context');

      return (
        <div
          ref={containerRef}
          className="acx-media-selection__media-alt-suggest"
          role="group"
          tabIndex={-1}
          aria-busy={isCommitInFlight ? true : undefined}
          aria-label={isCommitInFlight ? acceptingLabel : undefined}
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
                onChange={(event) => handleEditDraftChange(event.target.value)}
                disabled={isCommitInFlight}
                aria-describedby={editDescribedBy}
                aria-invalid={showCommitError || undefined}
              />
            </>
          ) : (
            <p className="acx-media-selection__media-alt-draft">{data.alt_text_draft}</p>
          )}
          <p id={disclosureId} className="acx-media-selection__media-alt-disclosure">
            {__('Drafted by AI — review before saving.', 'alt-context')}
          </p>
          {isOverLength ? (
            // Advisory only — not role="alert" (assertive channel is for save
            // failures) and not a second role="status" ([A11Y-19] / BR-32).
            // Does not disable Accept/Save ([A11Y-36]).
            <p id={lengthAdvisoryId} className="acx-media-selection__media-alt-length-advisory">
              {formatAltLengthAdvisory(commitCandidate.length)}
            </p>
          ) : null}
          {conflictMessage ? (
            <div id={errorId} className="acx-media-selection__media-alt-error" role="alert">
              {conflictMessage}
            </div>
          ) : isAcceptError ? (
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
                disabled={commitControlDisabled || !canSaveEdit}
              >
                {isAccepting && !isMarkingDecorative
                  ? __('Saving alt text…', 'alt-context')
                  : __('Save alt text', 'alt-context')}
              </button>
              <button
                type="button"
                className="button button-link acx-media-selection__media-alt-suggest-cancel"
                onClick={cancelEdit}
                disabled={isCommitInFlight}
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
                onClick={accept}
                disabled={commitControlDisabled || !canAcceptDraft}
                aria-describedby={showCommitError ? errorId : undefined}
              >
                {isAccepting && !isMarkingDecorative
                  ? __('Accepting draft…', 'alt-context')
                  : __('Accept', 'alt-context')}
              </button>
              <button
                type="button"
                ref={editButtonRef}
                className="button acx-media-selection__media-alt-suggest-edit"
                onClick={enterEditMode}
                disabled={isCommitInFlight}
              >
                {__('Edit draft', 'alt-context')}
              </button>
              <button
                type="button"
                className="button acx-media-selection__media-alt-suggest-regenerate"
                onClick={generate}
                disabled={isCommitInFlight}
              >
                {__('Regenerate', 'alt-context')}
              </button>
              <button
                type="button"
                ref={decorativeButtonRef}
                className="button acx-media-selection__media-alt-suggest-decorative"
                onClick={toggleDecorative}
                disabled={commitControlDisabled}
                aria-label={
                  isMarkingDecorative
                    ? undefined
                    : decorativeControlAriaLabel
                }
              >
                {isMarkingDecorative
                  ? decorativeBusyUnmarkingRef.current
                    ? __('Removing decorative mark…', 'alt-context')
                    : __('Marking as decorative…', 'alt-context')
                  : isDecorative
                    ? UNMARK_DECORATIVE_LABEL
                    : MARK_DECORATIVE_LABEL}
              </button>
              <button
                type="button"
                ref={dismissButtonRef}
                className="button button-link acx-media-selection__media-alt-suggest-dismiss"
                onClick={() => {
                  shouldFocusSuggestRef.current = true;
                  reset();
                  resetAccept();
                  setConflictMessage(null);
                  clearStatus();
                  setIsEditing(false);
                  wasOverLengthRef.current = false;
                }}
                disabled={isCommitInFlight}
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
        role="group"
        tabIndex={-1}
        aria-busy={isMarkingDecorative ? true : undefined}
        aria-label={
          isMarkingDecorative
            ? decorativeBusyUnmarkingRef.current
              ? __('Removing decorative mark…', 'alt-context')
              : __('Marking as decorative…', 'alt-context')
            : undefined
        }
        onBlur={handleContainerBlur}
      >
        <button
          type="button"
          ref={suggestButtonRef}
          className="button acx-media-selection__media-alt-suggest-trigger"
          onClick={generate}
          disabled={isMarkingDecorative}
          aria-label={suggestTriggerLabel}
        >
          {__('Suggest alt text', 'alt-context')}
        </button>
        <button
          type="button"
          ref={decorativeButtonRef}
          className="button acx-media-selection__media-alt-suggest-decorative"
          onClick={toggleDecorative}
          disabled={isMarkingDecorative || peerCommitPending}
          aria-label={
            isMarkingDecorative
              ? undefined
              : decorativeControlAriaLabel
          }
        >
          {isMarkingDecorative
            ? decorativeBusyUnmarkingRef.current
              ? __('Removing decorative mark…', 'alt-context')
              : __('Marking as decorative…', 'alt-context')
            : isDecorative
              ? UNMARK_DECORATIVE_LABEL
              : MARK_DECORATIVE_LABEL}
        </button>
        {conflictMessage ? (
          <div className="acx-media-selection__media-alt-error" role="alert">
            {conflictMessage}
          </div>
        ) : null}
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
