import React, { useMemo, useRef, useState } from 'react';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../components/ui/dialog';
import { GuidedPrototypeEntrance } from '../pages/GuidedPrototypeEntrance';
import { GuidedDesignNotes } from '../pages/guided/GuidedDesignNotes';
import { GuidedDescriptionReview } from '../pages/guided/GuidedDescriptionReview';
import { GuidedFaceMatchCard } from '../pages/guided/GuidedFaceMatchCard';
import { GuidedFacesPanel } from '../pages/guided/GuidedFacesPanel';
import { GuidedPhotoFaces } from '../pages/guided/GuidedPhotoFaces';
import { GuidedOutcome } from '../pages/guided/GuidedOutcome';
import { GuidedChoiceChangeDialog } from '../pages/guided/GuidedChoiceChangeDialog';
import {
  focusGuidedSection,
  guideStepsForScope,
  guidedStepLabelForScope,
  GuidedPrototypeGuide,
} from '../pages/guided/GuidedPrototypeGuide';
import { GuidedResetDialog } from '../pages/guided/GuidedResetDialog';
import { GuidedSamplePhoto } from '../pages/guided/GuidedSamplePhoto';
import { guidedCopy as adminGuidedCopy } from './copy';
import { guidedCopy as publicGuidedCopy } from './publicGuideCopy';
import {
  GUIDED_NAME_CHOICE,
  GUIDED_IMAGE_KEYS,
  GUIDED_STEP,
  GUIDED_OUTCOME,
  applyGuidedDraftForImage,
  canKeepCurrentForImage,
  cancelGuidedChoiceReplacement,
  chooseGuidedName,
  choicesForPhoto,
  confirmGuidedChoiceReplacement,
  createGuidedDemoState,
  createGuidedScenario,
  editGuidedDraftForImage,
  formatGuidedSimilarity,
  getGuidedPerson,
  GUIDED_MATCH_THRESHOLD,
  guidedNameCoverage,
  keepGuidedCurrentAltTextForImage,
  outcomeForPhoto,
  outcomeReady,
  previewGuidedDraftForImage,
  resetGuidedDemoState,
  restoreGuidedRevisionForImage,
  retryGuidedFixtureForImage,
  selectGuidedStep,
  undoGuidedApplicationForImage,
  type GuidedDemoState,
  type GuidedFacePosition,
  type GuidedImageKey,
  type GuidedNameChoice,
  type GuidedRestoreMode,
  type GuidedScenario,
  type GuidedStep,
} from './state';

export type RecordedWalkthroughScope = 'public' | 'admin';

export interface RecordedWalkthroughProps {
  scope: RecordedWalkthroughScope;
  livePanel?: React.ReactNode;
}

export const RecordedWalkthroughLiveSlot = React.createContext<((waiting: boolean) => void) | null>(null);

const lastSummary = (state: GuidedDemoState): string => state.actionHistory.at(-1)?.summary ?? '';

const choiceLabel = (scenario: GuidedScenario, position: GuidedFacePosition, choice: GuidedNameChoice): string => {
  const face = scenario.faces.find((candidate) => candidate.position === position);
  if (face === undefined) {
    return publicGuidedCopy('names.pending');
  }

  const person = getGuidedPerson(scenario, face.matchedPersonKey);
  switch (choice) {
    case GUIDED_NAME_CHOICE.USE:
      return publicGuidedCopy('names.use.public', { name: person.name });
    case GUIDED_NAME_CHOICE.LEAVE_UNNAMED:
      return publicGuidedCopy('names.omit.public');
    case GUIDED_NAME_CHOICE.UNANSWERED:
      return publicGuidedCopy('names.pending');
    default: {
      const exhaustive: never = choice;
      return exhaustive;
    }
  }
};

const publicChoiceSummary = (scenario: GuidedScenario, state: GuidedDemoState): string => {
  return GUIDED_IMAGE_KEYS.map((imageKey) => {
    const leftFace = scenario.faces.find(
      (candidate) => candidate.imageKey === imageKey && candidate.position === 'left',
    );
    const rightFace = scenario.faces.find(
      (candidate) => candidate.imageKey === imageKey && candidate.position === 'right',
    );
    if (leftFace === undefined || rightFace === undefined) {
      return publicGuidedCopy('feedback.choices.public', {
        leftName: 'Left face',
        leftChoice: publicGuidedCopy('names.pending'),
        rightName: 'Right face',
        rightChoice: publicGuidedCopy('names.pending'),
      });
    }

    const choices = choicesForPhoto(state, imageKey);
    return `${leftFace.imageKey}: ${publicGuidedCopy('feedback.choices.public', {
      leftName: getGuidedPerson(scenario, leftFace.matchedPersonKey).name,
      leftChoice: choiceLabel(scenario, 'left', choices.left),
      rightName: getGuidedPerson(scenario, rightFace.matchedPersonKey).name,
      rightChoice: choiceLabel(scenario, 'right', choices.right),
    })}`;
  }).join(' ');
};

const publicSourceSummary = (): React.ReactNode => {
  const source = publicGuidedCopy('context.source.summary.public');
  const vendor = 'AltText.ai';
  const vendorIndex = source.indexOf(vendor);
  if (vendorIndex < 0) {
    return source;
  }

  return (
    <>
      {source.slice(0, vendorIndex)}
      <a href="https://alttext.ai/" target="_blank" rel="noreferrer" aria-label={`${vendor} (opens in a new window)`}>
        {vendor}
      </a>
      {source.slice(vendorIndex + vendor.length)}
    </>
  );
};

interface GuidedChoiceReplacementDialogProps {
  open: boolean;
  onConfirmReplacement: () => void;
  onCancelReplacement: () => void;
}

const GuidedChoiceReplacementDialog = ({
  open,
  onConfirmReplacement,
  onCancelReplacement,
}: GuidedChoiceReplacementDialogProps): React.JSX.Element => (
  <DialogRoot
    open={open}
    onOpenChange={(nextOpen) => {
      if (!nextOpen) {
        onCancelReplacement();
      }
    }}
  >
    <DialogPortal>
      <DialogOverlay />
      <DialogContent
        aria-modal="true"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
        }}
      >
        <DialogTitle>{adminGuidedCopy('names.change_title')}</DialogTitle>
        <DialogDescription>{adminGuidedCopy('names.change_body')}</DialogDescription>
        <div className="acx-dialog__actions">
          <button type="button" className="acx-button acx-button--secondary" onClick={onCancelReplacement}>
            {adminGuidedCopy('names.change_cancel')}
          </button>
          <button type="button" className="acx-button acx-button--primary" onClick={onConfirmReplacement}>
            {adminGuidedCopy('names.change_confirm')}
          </button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
);

GuidedChoiceReplacementDialog.displayName = 'GuidedChoiceReplacementDialog';

interface PublicStartOverDialogProps {
  onConfirm: () => void;
  onFocusFirstNameQuestion: () => void;
}

const PublicStartOverDialog = ({
  onConfirm,
  onFocusFirstNameQuestion,
}: PublicStartOverDialogProps): React.JSX.Element => {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const focusScenarioAfterConfirmRef = useRef(false);
  const wasOpenRef = useRef(false);

  React.useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      return;
    }
    if (!wasOpenRef.current) {
      return;
    }
    wasOpenRef.current = false;
    if (focusScenarioAfterConfirmRef.current) {
      focusScenarioAfterConfirmRef.current = false;
      onFocusFirstNameQuestion();
      return;
    }
    triggerRef.current?.focus();
  }, [onFocusFirstNameQuestion, open]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="acx-button acx-button--tertiary"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        {publicGuidedCopy('reset.confirm.public')}
      </button>
      <DialogRoot open={open} onOpenChange={setOpen}>
        <DialogPortal>
          <DialogOverlay />
          <DialogContent
            aria-modal="true"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
            }}
          >
            <DialogTitle>{publicGuidedCopy('reset.title.public')}</DialogTitle>
            <DialogDescription>{publicGuidedCopy('reset.body.public')}</DialogDescription>
            <div className="acx-dialog__actions">
              <button
                type="button"
                className="acx-button acx-button--secondary"
                autoFocus
                onClick={() => setOpen(false)}
              >
                {publicGuidedCopy('reset.keep.public')}
              </button>
              <button
                type="button"
                className="acx-button acx-button--danger"
                onClick={() => {
                  focusScenarioAfterConfirmRef.current = true;
                  onConfirm();
                  setOpen(false);
                }}
              >
                {publicGuidedCopy('reset.confirm.public')}
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </>
  );
};

PublicStartOverDialog.displayName = 'PublicStartOverDialog';

export const RecordedWalkthroughAdmin = ({ scope, livePanel }: RecordedWalkthroughProps): React.JSX.Element => {
  const scenario = useMemo(() => createGuidedScenario(), []);
  const coverage = useMemo(() => guidedNameCoverage(scenario), [scenario]);
  const [demo, setDemo] = useState(createGuidedDemoState);
  const [guideOpen, setGuideOpen] = useState(true);
  const [feedback, setFeedback] = useState('');
  const [resetVersion, setResetVersion] = useState(0);
  const [liveWaiting, setLiveWaiting] = useState(false);
  const choiceOriginRef = useRef<HTMLInputElement | null>(null);
  const pendingDraftsByImageRef = useRef<Partial<Record<GuidedImageKey, string>>>({});

  const flushPendingDraft = (current: GuidedDemoState): GuidedDemoState => {
    let next = current;
    const pendingDrafts = pendingDraftsByImageRef.current;

    for (const imageKey of GUIDED_IMAGE_KEYS) {
      const pending = pendingDrafts[imageKey];
      if (pending === undefined || pending === (next.drafts[imageKey].draftText ?? '')) {
        continue;
      }
      next = editGuidedDraftForImage(next, imageKey, pending);
    }

    return next;
  };

  const commit = (next: GuidedDemoState, message?: string): void => {
    setDemo(next);
    setFeedback(message ?? lastSummary(next));
  };

  const handleFocusFirstNameQuestion = (): void => {
    document.querySelector<HTMLInputElement>('#guided-name-tribeca-left-include')?.focus({ preventScroll: true });
  };

  const guideProgressMessage = (step: GuidedStep): string => {
    const steps = guideStepsForScope(scope);
    const stepNumber = steps.indexOf(step) + 1;
    const stepTitle = guidedStepLabelForScope(step, scope);
    return adminGuidedCopy('guide.current', { stepNumber, stepTitle });
  };

  const handleBegin = (): void => {
    if (scope === 'admin') {
      commit(selectGuidedStep(flushPendingDraft(demo), GUIDED_STEP.CONTEXT), guideProgressMessage(GUIDED_STEP.CONTEXT));
      setGuideOpen(true);
      focusGuidedSection(GUIDED_STEP.CONTEXT);
      return;
    }
    commit(flushPendingDraft(demo));
  };

  const handleSelectStep = (step: GuidedStep): void => {
    commit(selectGuidedStep(flushPendingDraft(demo), step), guideProgressMessage(step));
  };

  const handleChoose = (
    imageKey: GuidedImageKey,
    position: GuidedFacePosition,
    choice: GuidedNameChoice,
    origin: HTMLInputElement,
  ): void => {
    choiceOriginRef.current = origin;
    commit(chooseGuidedName(flushPendingDraft(demo), scenario, position, choice, imageKey));
  };

  const handleCancelReplacement = (): void => {
    commit(cancelGuidedChoiceReplacement(demo));
    choiceOriginRef.current?.focus();
  };

  const handleConfirmReplacement = (): void => {
    commit(confirmGuidedChoiceReplacement(flushPendingDraft(demo), scenario));
    choiceOriginRef.current?.focus({ preventScroll: true });
  };

  const handleReturnToChangedChoice = (): void => {
    choiceOriginRef.current?.focus({ preventScroll: true });
  };

  const handlePreview = (imageKey: GuidedImageKey, text: string): void => {
    let next = demo;
    if (text !== (next.drafts[imageKey].draftText ?? '')) {
      next = editGuidedDraftForImage(next, imageKey, text);
    }
    next = previewGuidedDraftForImage(next, imageKey);
    commit(next);
    if (scope === 'public') {
      document
        .querySelector(`[data-testid="guided-description-review-${imageKey}"]`)
        ?.closest<HTMLElement>('[id="guided-section-apply"]')
        ?.focus({ preventScroll: true });
    } else {
      focusGuidedSection(GUIDED_STEP.APPLY);
    }
  };

  const handleKeep = (imageKey: GuidedImageKey): void => {
    const current = flushPendingDraft(demo);
    if (!canKeepCurrentForImage(current, imageKey) || current.drafts[imageKey].outcome === GUIDED_OUTCOME.APPLIED) {
      return;
    }
    commit(keepGuidedCurrentAltTextForImage(current, imageKey));
  };

  const handleReset = (): void => {
    pendingDraftsByImageRef.current = {};
    choiceOriginRef.current = null;
    setDemo(resetGuidedDemoState(demo));
    setResetVersion((current) => current + 1);
    setFeedback(scope === 'public' ? publicGuidedCopy('reset.success.public') : adminGuidedCopy('reset.status'));
  };

  const reviewActions = {
    onEdit: (imageKey: GuidedImageKey, text: string): void =>
      commit(editGuidedDraftForImage(flushPendingDraft(demo), imageKey, text)),
    onDraftInput: (imageKey: GuidedImageKey, text: string): void => {
      pendingDraftsByImageRef.current[imageKey] = text;
    },
    onPreview: handlePreview,
    onKeep: handleKeep,
    onRetryFixture: (imageKey: GuidedImageKey): void =>
      commit(retryGuidedFixtureForImage(flushPendingDraft(demo), imageKey, scenario)),
    onRestore: (imageKey: GuidedImageKey, revisionId: string, mode: GuidedRestoreMode): void =>
      commit(restoreGuidedRevisionForImage(flushPendingDraft(demo), imageKey, revisionId, mode)),
    onApply: (imageKey: GuidedImageKey, visibleText: string): void => {
      let next = flushPendingDraft(demo);
      if (visibleText !== (next.drafts[imageKey].draftText ?? '')) {
        next = editGuidedDraftForImage(next, imageKey, visibleText);
      }
      commit(applyGuidedDraftForImage(next, imageKey, scope === 'public' ? visibleText : undefined));
    },
    onUndo: (imageKey: GuidedImageKey): void =>
      commit(undoGuidedApplicationForImage(flushPendingDraft(demo), imageKey)),
  };

  const RootTag = scope === 'public' ? 'div' : 'main';

  return (
    <RootTag
      className="acx-guided-page"
      aria-labelledby="acx-guided-entrance-title"
      data-testid="guided-demo-root"
      data-scope={scope}
    >
      <GuidedPrototypeEntrance onBegin={handleBegin} scope={scope} />
      {scope === 'admin' ? (
        <GuidedPrototypeGuide
          activeStep={demo.activeStep}
          open={guideOpen}
          onToggle={() => setGuideOpen((current) => !current)}
          onSelect={handleSelectStep}
          scope="admin"
        />
      ) : null}
      <section className="acx-guided-page__workspace" aria-labelledby="acx-guided-page-title">
        <section
          id="guided-section-understand"
          className="acx-guided-page__understand"
          aria-labelledby="acx-guided-page-title"
          tabIndex={-1}
        >
          <header className="acx-guided-page__hero">
            <h2 id="acx-guided-page-title">
              {scope === 'public'
                ? publicGuidedCopy('photos.title.public')
                : guidedStepLabelForScope(GUIDED_STEP.CONTEXT, scope)}
            </h2>
            {scope === 'public' ? (
              <PublicStartOverDialog onConfirm={handleReset} onFocusFirstNameQuestion={handleFocusFirstNameQuestion} />
            ) : (
              <GuidedResetDialog liveWaiting={liveWaiting} onConfirm={handleReset} scope="admin" />
            )}
          </header>
          <div className="acx-guided-page__scenario">
            <div className="acx-guided-page__context">
              <p>{adminGuidedCopy('context.purpose')}</p>
            </div>
            <div className="acx-guided-page__media-list">
              {scenario.pressPhotos.map((photo, index) => {
                const photoContent = (
                  <GuidedSamplePhoto
                    key={photo.key}
                    photo={photo}
                    headingId={`guided-photo-${photo.key}-title`}
                    currentAltText={demo.drafts[photo.key].appliedAltText}
                    showCurrentAltText={index === 0}
                    scope={scope}
                  >
                    <GuidedPhotoFaces
                      photoKey={photo.key}
                      title={
                        scope === 'public'
                          ? publicGuidedCopy('names.heading.public')
                          : adminGuidedCopy('faces.group_title')
                      }
                    >
                      {scenario.faces
                        .filter((face) => face.imageKey === photo.key)
                        .map((face) => {
                          const person = getGuidedPerson(scenario, face.matchedPersonKey);
                          const personCoverage = coverage.find((entry) => entry.key === person.key);
                          if (personCoverage === undefined) {
                            throw new Error(`Missing guided name coverage for ${person.key}.`);
                          }

                          return (
                            <React.Fragment key={face.id}>
                              <GuidedFaceMatchCard
                                idScope={photo.key}
                                matches={scenario.faces
                                  .filter(
                                    (candidate) =>
                                      candidate.imageKey === photo.key &&
                                      candidate.matchedPersonKey === face.matchedPersonKey,
                                  )
                                  .map((match) => {
                                    const matchPhoto = scenario.pressPhotos.find(
                                      (candidate) => candidate.key === match.imageKey,
                                    );
                                    if (matchPhoto === undefined) {
                                      throw new Error(`Missing guided press photo for ${match.imageKey}.`);
                                    }
                                    return { face: match, mediaUrl: matchPhoto.src };
                                  })}
                                person={person}
                                coverage={personCoverage}
                                choice={choicesForPhoto(demo, photo.key)[face.position]}
                                disabled={demo.pendingChoiceChange !== null}
                                onChoose={(choice, origin, imageKey) =>
                                  handleChoose(imageKey, face.position, choice, origin)
                                }
                              />
                              {scope === 'admin' && face.similarity !== null ? (
                                <p className="acx-guided-face__match-line">
                                  {adminGuidedCopy('names.match.line', {
                                    name: person.name,
                                    similarity: formatGuidedSimilarity(face.similarity),
                                  })}
                                </p>
                              ) : null}
                              {scope === 'admin' &&
                              !face.isClusterAnchor &&
                              face.similarity !== null &&
                              face.similarity < GUIDED_MATCH_THRESHOLD ? (
                                <p>
                                  {adminGuidedCopy('names.match.below_threshold', {
                                    threshold: formatGuidedSimilarity(GUIDED_MATCH_THRESHOLD),
                                  })}
                                </p>
                              ) : null}
                            </React.Fragment>
                          );
                        })}
                      {scope === 'public' ? (
                        <GuidedDescriptionReview
                          scenario={{ ...scenario, pressPhotos: [photo] }}
                          state={demo}
                          scope="public"
                          recordedOriginLabel={publicGuidedCopy('draft.origin.public')}
                          actions={reviewActions}
                        />
                      ) : null}
                    </GuidedPhotoFaces>
                  </GuidedSamplePhoto>
                );

                return scope === 'public' ? (
                  <section
                    key={photo.key}
                    className="acx-guided-page__photo-step"
                    data-testid={`guided-photo-step-${photo.key}`}
                    aria-labelledby={`guided-photo-step-${photo.key}-title`}
                  >
                    <h3 id={`guided-photo-step-${photo.key}-title`}>
                      {publicGuidedCopy('photo.count.public', { photoNumber: index + 1 })}
                    </h3>
                    {photoContent}
                  </section>
                ) : (
                  photoContent
                );
              })}
            </div>
            <div className="acx-guided-page__provenance-footer">
              {scope === 'public' ? (
                <>
                  <p>{publicSourceSummary()}</p>
                  <p>{publicGuidedCopy('context.source.comparison_boundary.public')}</p>
                </>
              ) : null}
              <p>{adminGuidedCopy('provenance.recorded')}</p>
            </div>
            {scope === 'admin' ? (
              <button
                type="button"
                className="acx-button acx-button--primary"
                onClick={() => {
                  handleSelectStep(GUIDED_STEP.NAMES);
                  focusGuidedSection(GUIDED_STEP.NAMES);
                }}
              >
                {adminGuidedCopy('context.next')}
              </button>
            ) : null}
          </div>
        </section>

        <p className="acx-guided-page__feedback" data-testid="guided-page-feedback">
          {scope === 'public' ? (
            <span className="acx-guided-page__choice-summary" data-testid="guided-choice-summary">
              {publicChoiceSummary(scenario, demo)}
            </span>
          ) : null}
          <span
            className="acx-guided-page__feedback-status"
            data-testid="guided-page-feedback-status"
            role="status"
            aria-live="polite"
          >
            {feedback ? (
              <span
                className="acx-guided-page__feedback-icon"
                aria-hidden="true"
                data-testid="guided-page-feedback-icon"
              />
            ) : null}
            {feedback}
          </span>
        </p>

        {scope === 'admin' ? (
          <GuidedFacesPanel
            scenario={scenario}
            state={demo}
            onChoose={(position, choice, origin) => handleChoose('tribeca', position, choice, origin)}
            onContinue={() => {
              handleSelectStep(GUIDED_STEP.DRAFT);
              focusGuidedSection(GUIDED_STEP.DRAFT);
            }}
          />
        ) : null}

        {scope === 'public' ? (
          <GuidedChoiceChangeDialog
            open={demo.pendingChoiceChange !== null}
            onKeepEdits={handleCancelReplacement}
            onChangeName={handleConfirmReplacement}
            onReturnFocus={handleReturnToChangedChoice}
          />
        ) : (
          <GuidedChoiceReplacementDialog
            open={demo.pendingChoiceChange !== null}
            onConfirmReplacement={handleConfirmReplacement}
            onCancelReplacement={handleCancelReplacement}
          />
        )}

        {scope === 'admin' ? (
          <GuidedDescriptionReview scenario={scenario} state={demo} scope="admin" actions={reviewActions} />
        ) : null}

        {scope === 'public' && outcomeReady(demo) ? (
          <GuidedOutcome
            outcomes={{
              tribeca: outcomeForPhoto(demo, 'tribeca'),
              coachella: outcomeForPhoto(demo, 'coachella'),
            }}
            outcomeReady
            scope={scope}
            onReturn={() => {
              focusGuidedSection(GUIDED_STEP.DRAFT);
            }}
          />
        ) : null}
        {scope === 'admin' ? (
          <GuidedOutcome
            outcome={demo.outcome}
            scope="admin"
            onReturn={() => {
              focusGuidedSection(GUIDED_STEP.DRAFT);
            }}
          />
        ) : null}

        {scope === 'admin' ? (
          <>
            <section className="acx-guided-history" aria-labelledby="acx-guided-history-title">
              <h2 id="acx-guided-history-title">{adminGuidedCopy('history.title')}</h2>
              <p>{adminGuidedCopy('history.scope')}</p>
              {demo.actionHistory.length === 0 ? (
                <p>{adminGuidedCopy('history.empty')}</p>
              ) : (
                <ol>
                  {demo.actionHistory.map((entry) => (
                    <li key={`${entry.event}-${entry.sequence}`}>{entry.summary}</li>
                  ))}
                </ol>
              )}
            </section>

            <GuidedDesignNotes scope={scope} />
          </>
        ) : null}

        {livePanel != null ? (
          <RecordedWalkthroughLiveSlot.Provider value={setLiveWaiting}>
            <React.Fragment key={resetVersion}>{livePanel}</React.Fragment>
          </RecordedWalkthroughLiveSlot.Provider>
        ) : null}
      </section>
    </RootTag>
  );
};

RecordedWalkthroughAdmin.displayName = 'RecordedWalkthroughAdmin';
