import {
  GUIDED_DRAFT_ORIGIN,
  GUIDED_DRAFT_STATUS,
  GUIDED_NAME_CHOICE,
  GUIDED_OUTCOME,
  GUIDED_STEP,
  type GuidedApplicationRecord,
  type GuidedChoices,
  type GuidedDemoState,
  type GuidedDraftOrigin,
  type GuidedDraftRevision,
  type GuidedDraftStatus,
  type GuidedImageKey,
  type GuidedPendingChoiceChange,
  type GuidedRestoreMode,
} from './state';

/**
 * The part of a demo state that belongs to one image's review card.
 *
 * Keeping this shape next to the review UI lets the component consume the
 * per-image state while the walkthrough migrates from its original single
 * draft shape. `draftVersion` and `previewedVersion` are optional because
 * older saved state did not keep those counters inside the draft record.
 */
export interface GuidedImageDraft {
  draftText: string | null;
  draftOrigin: GuidedDraftOrigin;
  draftStatus: GuidedDraftStatus;
  draftVersion?: number;
  previewedVersion?: number | null;
  appliedAltText: string;
  applicationHistory: GuidedApplicationRecord[];
  draftHistory: GuidedDraftRevision[];
}

/**
 * Structural state contract used by the review components. It deliberately
 * keeps the walkthrough fields optional so the UI remains source-compatible
 * with the pre-migration `GuidedDemoState` while the reducer is being wired.
 */
export interface GuidedReviewState {
  choices: GuidedChoices;
  pendingChoiceChange: GuidedPendingChoiceChange | null;
  drafts?: Partial<Record<GuidedImageKey, GuidedImageDraft>>;
  draftText?: string | null;
  draftOrigin?: GuidedDraftOrigin;
  draftStatus?: GuidedDraftStatus;
  draftVersion?: number;
  previewedVersion?: number | null;
  draftHistory?: GuidedDraftRevision[];
  appliedAltText?: string;
  applicationUndoStack?: GuidedApplicationRecord[];
}

export type GuidedTextAction = ((text: string) => void) | ((imageKey: GuidedImageKey, text: string) => void);

export type GuidedImageAction = (() => void) | ((imageKey: GuidedImageKey) => void);

export type GuidedRestoreAction =
  | ((revisionId: string, mode: GuidedRestoreMode) => void)
  | ((imageKey: GuidedImageKey, revisionId: string, mode: GuidedRestoreMode) => void);

export const GUIDED_REVIEW_TRIBECA_KEY: GuidedImageKey = 'tribeca';
export const GUIDED_REVIEW_COACHELLA_KEY: GuidedImageKey = 'coachella';
const GUIDED_REVIEW_IMAGE_KEYS: readonly GuidedImageKey[] = [GUIDED_REVIEW_TRIBECA_KEY, GUIDED_REVIEW_COACHELLA_KEY];

const isDraftRecord = (value: unknown): value is GuidedImageDraft => {
  if (value === null || typeof value !== 'object') {
    return false;
  }
  const draft = value as Partial<GuidedImageDraft>;
  return (
    (typeof draft.draftText === 'string' || draft.draftText === null) &&
    typeof draft.draftOrigin === 'string' &&
    typeof draft.draftStatus === 'string' &&
    typeof draft.appliedAltText === 'string' &&
    Array.isArray(draft.applicationHistory) &&
    Array.isArray(draft.draftHistory)
  );
};

/** True when the reducer has supplied a complete per-image draft map. */
export const hasGuidedImageDrafts = (
  state: GuidedReviewState,
): state is GuidedReviewState & { drafts: Record<GuidedImageKey, GuidedImageDraft> } =>
  state.drafts !== undefined && GUIDED_REVIEW_IMAGE_KEYS.every((imageKey) => isDraftRecord(state.drafts?.[imageKey]));

const emptyDraft = (): GuidedImageDraft => ({
  draftText: null,
  draftOrigin: GUIDED_DRAFT_ORIGIN.NONE,
  draftStatus: GUIDED_DRAFT_STATUS.BLOCKED,
  draftVersion: 0,
  previewedVersion: null,
  appliedAltText: '',
  applicationHistory: [],
  draftHistory: [],
});

const normalizedDraft = (draft: GuidedImageDraft): GuidedImageDraft => ({
  ...draft,
  draftVersion: draft.draftVersion ?? 0,
  previewedVersion: draft.previewedVersion ?? null,
  applicationHistory: [...draft.applicationHistory],
  draftHistory: [...draft.draftHistory],
});

/**
 * Read one image's draft from either the new state shape or the old single
 * draft shape. The latter is mapped to Tribeca so existing callers keep their
 * behaviour until the walkthrough passes image-aware actions.
 */
export const guidedReviewDraftFor = (state: GuidedReviewState, imageKey: GuidedImageKey): GuidedImageDraft | null => {
  const perImageDraft = state.drafts?.[imageKey];
  if (perImageDraft !== undefined && isDraftRecord(perImageDraft)) {
    return normalizedDraft(perImageDraft);
  }
  if (imageKey !== GUIDED_REVIEW_TRIBECA_KEY) {
    return null;
  }

  return {
    draftText: state.draftText ?? null,
    draftOrigin: state.draftOrigin ?? GUIDED_DRAFT_ORIGIN.NONE,
    draftStatus: state.draftStatus ?? GUIDED_DRAFT_STATUS.BLOCKED,
    draftVersion: state.draftVersion ?? 0,
    previewedVersion: state.previewedVersion ?? null,
    appliedAltText: state.appliedAltText ?? '',
    applicationHistory: [...(state.applicationUndoStack ?? [])],
    draftHistory: [...(state.draftHistory ?? [])],
  };
};

const toGuidedDemoDraft = (draft: GuidedImageDraft): GuidedDemoState['drafts'][GuidedImageKey] => ({
  draftText: draft.draftText,
  draftOrigin: draft.draftOrigin,
  draftStatus: draft.draftStatus,
  draftVersion: draft.draftVersion ?? 0,
  previewedVersion: draft.previewedVersion ?? null,
  appliedAltText: draft.appliedAltText,
  applicationHistory: [...draft.applicationHistory],
  draftHistory: [...draft.draftHistory],
});

/**
 * Build the legacy state shape required by the public draft eligibility
 * predicate while the review state migration is in progress.
 */
export const guidedReviewLegacyState = (state: GuidedReviewState): GuidedDemoState => {
  const tribeca = guidedReviewDraftFor(state, GUIDED_REVIEW_TRIBECA_KEY) ?? emptyDraft();
  const coachella = guidedReviewDraftFor(state, GUIDED_REVIEW_COACHELLA_KEY) ?? emptyDraft();
  return {
    activeStep: GUIDED_STEP.APPLY,
    choices: state.choices,
    drafts: {
      tribeca: toGuidedDemoDraft(tribeca),
      coachella: toGuidedDemoDraft(coachella),
    },
    draftText: tribeca.draftText,
    draftOrigin: tribeca.draftOrigin,
    draftStatus: tribeca.draftStatus,
    draftVersion: tribeca.draftVersion ?? 0,
    previewedVersion: tribeca.previewedVersion ?? null,
    draftHistory: [...tribeca.draftHistory],
    pendingChoiceChange: state.pendingChoiceChange,
    appliedAltText: tribeca.appliedAltText,
    applicationUndoStack: [...tribeca.applicationHistory],
    outcome: GUIDED_OUTCOME.NOT_FINISHED,
    actionHistory: [],
  };
};

export const guidedReviewNamesDecided = (state: GuidedReviewState): boolean =>
  state.choices.left !== GUIDED_NAME_CHOICE.UNDECIDED && state.choices.right !== GUIDED_NAME_CHOICE.UNDECIDED;

export const guidedReviewCanPreview = (state: GuidedReviewState, draft: GuidedImageDraft): boolean =>
  guidedReviewNamesDecided(state) &&
  draft.draftStatus === GUIDED_DRAFT_STATUS.READY &&
  draft.draftText !== null &&
  draft.draftText.trim().length > 0;

export const guidedReviewCanApply = (state: GuidedReviewState, draft: GuidedImageDraft): boolean =>
  guidedReviewCanPreview(state, draft) &&
  draft.previewedVersion === draft.draftVersion &&
  draft.draftText !== draft.appliedAltText &&
  state.pendingChoiceChange === null;

export const guidedReviewCanUndo = (draft: GuidedImageDraft): boolean => draft.applicationHistory.length > 0;

export const guidedReviewCanRestore = (
  state: GuidedReviewState,
  draft: GuidedImageDraft,
  revisionId: string,
): boolean => {
  const revision = draft.draftHistory.find((entry) => entry.revisionId === revisionId);
  if (revision === undefined) {
    return false;
  }
  return revision.choices.left === state.choices.left && revision.choices.right === state.choices.right;
};

export const guidedReviewImageKeys = (): readonly GuidedImageKey[] => GUIDED_REVIEW_IMAGE_KEYS;
