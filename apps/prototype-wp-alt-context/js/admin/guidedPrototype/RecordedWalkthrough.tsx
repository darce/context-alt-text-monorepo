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
import { GuidedPhotoFaces } from '../pages/guided/GuidedPhotoFaces';
import { GuidedOutcome } from '../pages/guided/GuidedOutcome';
import { GuidedChoiceChangeDialog } from '../pages/guided/GuidedChoiceChangeDialog';
import { focusGuidedSection } from '../pages/guided/GuidedPrototypeGuide';
import { GuidedResetDialog } from '../pages/guided/GuidedResetDialog';
import { GuidedSamplePhoto } from '../pages/guided/GuidedSamplePhoto';
import { guidedCopy } from './publicGuideCopy';
import {
  GUIDED_NAME_CHOICE,
  GUIDED_IMAGE_KEYS,
  GUIDED_STEP,
  applyGuidedDraftForImage,
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
  bothNamesAnswered,
  guidedNameCoverage,
  keepGuidedCurrentAltTextForImage,
  outcomeForPhoto,
  outcomeReady,
  previewGuidedDraftForImage,
  resetGuidedDemoState,
  restoreGuidedRevisionForImage,
  retryGuidedFixtureForImage,
  undoGuidedApplicationForImage,
  type GuidedDemoState,
  type GuidedFacePosition,
  type GuidedImageKey,
  type GuidedNameChoice,
  type GuidedRestoreMode,
  type GuidedScenario,
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
    return guidedCopy('names.pending');
  }

  const person = getGuidedPerson(scenario, face.matchedPersonKey);
  switch (choice) {
    case GUIDED_NAME_CHOICE.USE:
      return guidedCopy('names.use.public', { name: person.name });
    case GUIDED_NAME_CHOICE.LEAVE_UNNAMED:
      return guidedCopy('names.omit.public');
    case GUIDED_NAME_CHOICE.UNANSWERED:
      return guidedCopy('names.pending');
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
      return guidedCopy('feedback.choices.public', {
        leftName: 'Left face',
        leftChoice: guidedCopy('names.pending'),
        rightName: 'Right face',
        rightChoice: guidedCopy('names.pending'),
      });
    }

    const choices = choicesForPhoto(state, imageKey);
    return `${leftFace.imageKey}: ${guidedCopy('feedback.choices.public', {
      leftName: getGuidedPerson(scenario, leftFace.matchedPersonKey).name,
      leftChoice: choiceLabel(scenario, 'left', choices.left),
      rightName: getGuidedPerson(scenario, rightFace.matchedPersonKey).name,
      rightChoice: choiceLabel(scenario, 'right', choices.right),
    })}`;
  }).join(' ');
};

const publicSourceSummary = (): React.ReactNode => {
  const source = guidedCopy('context.source.summary.public');
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
        <DialogTitle>{guidedCopy('names.change_title')}</DialogTitle>
        <DialogDescription>{guidedCopy('names.change_body')}</DialogDescription>
        <div className="acx-dialog__actions">
          <button type="button" className="acx-button acx-button--secondary" onClick={onCancelReplacement}>
            {guidedCopy('names.change_cancel')}
          </button>
          <button type="button" className="acx-button acx-button--primary" onClick={onConfirmReplacement}>
            {guidedCopy('names.change_confirm')}
          </button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
);

GuidedChoiceReplacementDialog.displayName = 'GuidedChoiceReplacementDialog';

interface PublicStartOverDialogProps {
  onConfirm: () => void;
}

const PublicStartOverDialog = ({ onConfirm }: PublicStartOverDialogProps): React.JSX.Element => {
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
      focusGuidedSection(GUIDED_STEP.CONTEXT);
      return;
    }
    triggerRef.current?.focus();
  }, [open]);

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
        {guidedCopy('reset.confirm.public')}
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
            <DialogTitle>{guidedCopy('reset.title.public')}</DialogTitle>
            <DialogDescription>{guidedCopy('reset.body.public')}</DialogDescription>
            <div className="acx-dialog__actions">
              <button
                type="button"
                className="acx-button acx-button--secondary"
                autoFocus
                onClick={() => setOpen(false)}
              >
                {guidedCopy('reset.keep.public')}
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
                {guidedCopy('reset.confirm.public')}
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </>
  );
};

PublicStartOverDialog.displayName = 'PublicStartOverDialog';

export const RecordedWalkthrough = ({ scope, livePanel }: RecordedWalkthroughProps): React.JSX.Element => {
  const scenario = useMemo(() => createGuidedScenario(), []);
  const coverage = useMemo(() => guidedNameCoverage(scenario), [scenario]);
  const [demo, setDemo] = useState(createGuidedDemoState);
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

  const handleBegin = (): void => {
    commit(flushPendingDraft(demo));
    if (scope === 'admin') {
      handleFocusFirstNameQuestion();
    }
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
    focusGuidedSection(GUIDED_STEP.DRAFT);
  };

  const handlePreview = (imageKey: GuidedImageKey, text: string): void => {
    let next = demo;
    if (text !== (next.drafts[imageKey].draftText ?? '')) {
      next = editGuidedDraftForImage(next, imageKey, text);
    }
    next = previewGuidedDraftForImage(next, imageKey);
    commit(next);
    focusGuidedSection(GUIDED_STEP.APPLY);
  };

  const handleReset = (): void => {
    pendingDraftsByImageRef.current = {};
    choiceOriginRef.current = null;
    setDemo(resetGuidedDemoState(demo));
    setResetVersion((current) => current + 1);
    setFeedback(guidedCopy(scope === 'public' ? 'reset.success.public' : 'reset.status'));
  };

  const RootTag = scope === 'public' ? 'div' : 'main';

  return (
    <RootTag
      className="acx-guided-page"
      aria-labelledby="acx-guided-entrance-title"
      data-testid="guided-demo-root"
      data-scope={scope}
    >
      <GuidedPrototypeEntrance
        onBegin={handleBegin}
        onFocusFirstNameQuestion={handleFocusFirstNameQuestion}
        scope={scope}
      />
      <section className="acx-guided-page__workspace" aria-labelledby="acx-guided-page-title">
        <section
          id="guided-section-understand"
          className="acx-guided-page__understand"
          aria-labelledby="acx-guided-page-title"
          tabIndex={-1}
        >
          <header className="acx-guided-page__hero">
            <h2 id="acx-guided-page-title">{guidedCopy('photos.title.public')}</h2>
            {scope === 'public' ? (
              <PublicStartOverDialog onConfirm={handleReset} />
            ) : (
              <GuidedResetDialog liveWaiting={liveWaiting} onConfirm={handleReset} scope="admin" />
            )}
          </header>
          <div className="acx-guided-page__scenario">
            <div className="acx-guided-page__context">
              <p>{guidedCopy('context.purpose')}</p>
            </div>
            <div className="acx-guided-page__media-list">
              {scenario.pressPhotos.map((photo, index) => (
                <section
                  key={photo.key}
                  className="acx-guided-page__photo-step"
                  data-testid={`guided-photo-step-${photo.key}`}
                  aria-labelledby={`guided-photo-step-${photo.key}-title`}
                >
                  <h3 id={`guided-photo-step-${photo.key}-title`}>
                    {guidedCopy('photo.count.public', { photoNumber: index + 1 })}
                  </h3>
                  <GuidedSamplePhoto
                    photo={photo}
                    headingId={`guided-photo-${photo.key}-title`}
                    currentAltText={demo.drafts[photo.key].appliedAltText}
                    showCurrentAltText={index === 0}
                    scope={scope}
                  >
                    <GuidedPhotoFaces
                      photoKey={photo.key}
                      title={guidedCopy('names.heading.public')}
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
                                  {guidedCopy('names.match.line', {
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
                                  {guidedCopy('names.match.below_threshold', {
                                    threshold: formatGuidedSimilarity(GUIDED_MATCH_THRESHOLD),
                                  })}
                                </p>
                              ) : null}
                            </React.Fragment>
                          );
                        })}
                      <section
                        className="acx-guided-page__description-step"
                        data-testid={`guided-description-step-${photo.key}`}
                        aria-labelledby={`guided-description-step-${photo.key}-title`}
                      >
                        <h4 id={`guided-description-step-${photo.key}-title`}>
                          {guidedCopy('description.heading.public')}
                        </h4>
                        <p>
                          {bothNamesAnswered(demo, photo.key)
                            ? guidedCopy('description.written.public')
                            : guidedCopy('description.help.public')}
                        </p>
                      </section>
                    </GuidedPhotoFaces>
                  </GuidedSamplePhoto>
                </section>
              ))}
            </div>
            <div className="acx-guided-page__provenance-footer">
              {scope === 'public' ? (
                <>
                  <p>{publicSourceSummary()}</p>
                  <p>{guidedCopy('context.source.comparison_boundary.public')}</p>
                </>
              ) : null}
              <p>{guidedCopy('provenance.recorded')}</p>
            </div>
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

        {scope === 'public' ? (
          <GuidedChoiceChangeDialog
            open={demo.pendingChoiceChange !== null}
            onKeepEdits={handleCancelReplacement}
            onChangeName={handleConfirmReplacement}
          />
        ) : (
          <GuidedChoiceReplacementDialog
            open={demo.pendingChoiceChange !== null}
            onConfirmReplacement={handleConfirmReplacement}
            onCancelReplacement={handleCancelReplacement}
          />
        )}

        <GuidedDescriptionReview
          scenario={scenario}
          state={demo}
          scope={scope}
          {...(scope === 'public' ? { recordedOriginLabel: guidedCopy('draft.origin.public') } : {})}
          actions={{
            onEdit: (imageKey, text) =>
              commit(editGuidedDraftForImage(flushPendingDraft(demo), imageKey, text)),
            onDraftInput: (imageKey, text) => {
              pendingDraftsByImageRef.current[imageKey] = text;
            },
            onPreview: handlePreview,
            onKeep: (imageKey) =>
              commit(keepGuidedCurrentAltTextForImage(flushPendingDraft(demo), imageKey)),
            onRetryFixture: (imageKey) =>
              commit(retryGuidedFixtureForImage(flushPendingDraft(demo), imageKey, scenario)),
            onRestore: (imageKey, revisionId: string, mode: GuidedRestoreMode) =>
              commit(restoreGuidedRevisionForImage(flushPendingDraft(demo), imageKey, revisionId, mode)),
            onApply: (imageKey, visibleText) => {
              let next = flushPendingDraft(demo);
              if (visibleText !== (next.drafts[imageKey].draftText ?? '')) {
                next = editGuidedDraftForImage(next, imageKey, visibleText);
              }
              commit(
                applyGuidedDraftForImage(
                  next,
                  imageKey,
                  scope === 'public' ? visibleText : undefined,
                ),
              );
            },
            onUndo: (imageKey) =>
              commit(undoGuidedApplicationForImage(flushPendingDraft(demo), imageKey)),
          }}
        />

        {outcomeReady(demo) ? (
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
          <>
            <section className="acx-guided-history" aria-labelledby="acx-guided-history-title">
              <h2 id="acx-guided-history-title">{guidedCopy('history.title')}</h2>
              <p>{guidedCopy('history.scope')}</p>
              {demo.actionHistory.length === 0 ? (
                <p>{guidedCopy('history.empty')}</p>
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

RecordedWalkthrough.displayName = 'RecordedWalkthrough';
