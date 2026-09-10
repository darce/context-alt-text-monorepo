import React, { useMemo, useRef, useState } from 'react';

import { GuidedPrototypeEntrance } from '../pages/GuidedPrototypeEntrance';
import { GuidedDesignNotes } from '../pages/guided/GuidedDesignNotes';
import { GuidedDescriptionReview } from '../pages/guided/GuidedDescriptionReview';
import { GuidedFacesPanel } from '../pages/guided/GuidedFacesPanel';
import { GuidedOutcome } from '../pages/guided/GuidedOutcome';
import { focusGuidedSection, guidedStepLabel, GuidedPrototypeGuide } from '../pages/guided/GuidedPrototypeGuide';
import { GuidedResetDialog } from '../pages/guided/GuidedResetDialog';
import { GuidedSamplePhoto } from '../pages/guided/GuidedSamplePhoto';
import { guidedCopy } from './publicGuideCopy';
import {
  GUIDED_NAME_CHOICE,
  GUIDED_STEP,
  guidedStepIndex,
  applyGuidedDraft,
  cancelGuidedChoiceReplacement,
  chooseGuidedName,
  confirmGuidedChoiceReplacement,
  createGuidedDemoState,
  createGuidedScenario,
  editGuidedDraft,
  getGuidedPerson,
  keepGuidedCurrentAltText,
  previewGuidedDraft,
  resetGuidedDemoState,
  restoreGuidedRevision,
  retryGuidedFixture,
  selectGuidedStep,
  undoGuidedApplication,
  type GuidedDemoState,
  type GuidedFacePosition,
  type GuidedNameChoice,
  type GuidedRestoreMode,
  type GuidedScenario,
  type GuidedStep,
} from './state';

export type RecordedWalkthroughScope = 'public' | 'admin';

export interface RecordedWalkthroughProps {
  scope: RecordedWalkthroughScope;
  livePanel?: React.ReactNode;
  escapeHref?: string;
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
    case GUIDED_NAME_CHOICE.INCLUDE:
      return guidedCopy('names.include', { name: person.name });
    case GUIDED_NAME_CHOICE.OMIT:
      return guidedCopy('names.omit');
    case GUIDED_NAME_CHOICE.UNDECIDED:
      return guidedCopy('names.pending');
    default: {
      const exhaustive: never = choice;
      return exhaustive;
    }
  }
};

const publicChoiceSummary = (scenario: GuidedScenario, state: GuidedDemoState): string => {
  const leftFace = scenario.faces.find((candidate) => candidate.position === 'left');
  const rightFace = scenario.faces.find((candidate) => candidate.position === 'right');
  if (leftFace === undefined || rightFace === undefined) {
    return guidedCopy('feedback.choices.public', {
      leftName: 'Left face',
      leftChoice: guidedCopy('names.pending'),
      rightName: 'Right face',
      rightChoice: guidedCopy('names.pending'),
    });
  }

  return guidedCopy('feedback.choices.public', {
    leftName: getGuidedPerson(scenario, leftFace.matchedPersonKey).name,
    leftChoice: choiceLabel(scenario, 'left', state.choices.left),
    rightName: getGuidedPerson(scenario, rightFace.matchedPersonKey).name,
    rightChoice: choiceLabel(scenario, 'right', state.choices.right),
  });
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
      <a
        href="https://alttext.ai/"
        target="_blank"
        rel="noreferrer"
        aria-label={`${vendor} (opens in a new window)`}
      >
        {vendor}
      </a>
      {source.slice(vendorIndex + vendor.length)}
    </>
  );
};

export const RecordedWalkthrough = ({ scope, livePanel, escapeHref }: RecordedWalkthroughProps): React.JSX.Element => {
  const scenario = useMemo(() => createGuidedScenario(), []);
  const [demo, setDemo] = useState(createGuidedDemoState);
  const [guideOpen, setGuideOpen] = useState(true);
  const [feedback, setFeedback] = useState('');
  const [resetVersion, setResetVersion] = useState(0);
  const [liveWaiting, setLiveWaiting] = useState(false);
  const choiceOriginRef = useRef<HTMLInputElement | null>(null);
  const pendingDraftRef = useRef<string | null>(null);

  const flushPendingDraft = (current: GuidedDemoState): GuidedDemoState => {
    const pending = pendingDraftRef.current;
    if (pending === null || pending === (current.draftText ?? '')) {
      return current;
    }
    return editGuidedDraft(current, pending);
  };

  const commit = (next: GuidedDemoState, message?: string): void => {
    setDemo(next);
    setFeedback(message ?? lastSummary(next));
  };

  const handleBegin = (): void => {
    commit(
      selectGuidedStep(demo, GUIDED_STEP.CONTEXT),
      guidedCopy('guide.current', {
        stepNumber: 1,
        stepTitle: guidedCopy('step.context'),
      }),
    );
    setGuideOpen(true);
    focusGuidedSection(GUIDED_STEP.CONTEXT);
  };

  const handleSelectStep = (step: GuidedStep): void => {
    commit(
      selectGuidedStep(demo, step),
      guidedCopy('guide.current', {
        stepNumber: guidedStepIndex(step) + 1,
        stepTitle: guidedStepLabel(step),
      }),
    );
  };

  const handleChoose = (position: GuidedFacePosition, choice: GuidedNameChoice, origin: HTMLInputElement): void => {
    choiceOriginRef.current = origin;
    commit(chooseGuidedName(flushPendingDraft(demo), scenario, position, choice));
  };

  const handleCancelReplacement = (): void => {
    commit(cancelGuidedChoiceReplacement(demo));
    choiceOriginRef.current?.focus();
  };

  const handlePreview = (text: string): void => {
    let next = demo;
    if (text !== (next.draftText ?? '')) {
      next = editGuidedDraft(next, text);
    }
    next = previewGuidedDraft(next);
    commit(next);
    focusGuidedSection(GUIDED_STEP.APPLY);
  };

  const handleReset = (): void => {
    pendingDraftRef.current = null;
    choiceOriginRef.current = null;
    setDemo(resetGuidedDemoState(demo));
    setResetVersion((current) => current + 1);
    setFeedback(guidedCopy('reset.status'));
  };

  const RootTag = scope === 'public' ? 'div' : 'main';

  return (
    <RootTag
      className="acx-guided-page"
      aria-labelledby="acx-guided-entrance-title"
      data-testid="guided-demo-root"
      data-scope={scope}
      {...(escapeHref !== undefined ? { 'data-escape-href': escapeHref } : {})}
    >
      <GuidedPrototypeEntrance onBegin={handleBegin} scope={scope} escapeHref={escapeHref} />
      <GuidedPrototypeGuide
        activeStep={demo.activeStep}
        open={guideOpen}
        onToggle={() => setGuideOpen((current) => !current)}
        onSelect={handleSelectStep}
      />

      <section className="acx-guided-page__workspace" aria-labelledby="acx-guided-page-title">
        <section
          id="guided-section-understand"
          className="acx-guided-page__understand"
          aria-labelledby="acx-guided-page-title"
          tabIndex={-1}
        >
          <header className="acx-guided-page__hero">
            <h2 id="acx-guided-page-title">{guidedCopy('step.context')}</h2>
            <GuidedResetDialog liveWaiting={liveWaiting} onConfirm={handleReset} />
          </header>
          <div className="acx-guided-page__scenario">
            <GuidedSamplePhoto
              src={scenario.pressPhoto.src}
              evidenceAlt={scenario.samples.none ?? scenario.pressPhoto.altText}
              currentAltText={demo.appliedAltText}
              credit={scenario.pressPhoto.credit}
            />
            <div className="acx-guided-page__context">
              <p>{guidedCopy('context.intro')}</p>
              <p>
                <strong>{guidedCopy('context.page_label')}</strong>
                {': '}
                {scenario.pageContext.title}
              </p>
              <p>{scenario.pageContext.summary}</p>
              <p>{guidedCopy('context.purpose')}</p>
              <details className="acx-guided-page__provenance">
                <summary>{guidedCopy('provenance.disclosure')}</summary>
                {scope === 'public' ? (
                  <>
                    <p>{publicSourceSummary()}</p>
                    <p>{guidedCopy('context.source.comparison_boundary.public')}</p>
                  </>
                ) : null}
                <p>{guidedCopy('provenance.recorded')}</p>
                <p>{scenario.pressPhoto.credit}</p>
              </details>
              <button
                type="button"
                className="acx-button acx-button--primary"
                onClick={() => {
                  handleSelectStep(GUIDED_STEP.NAMES);
                  focusGuidedSection(GUIDED_STEP.NAMES);
                }}
              >
                {guidedCopy('context.next')}
              </button>
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
          <aside className="acx-guided-review__explanation" data-testid="public-roster-explainer">
            <h2>{guidedCopy('roster.explainer.title')}</h2>
            <p>{guidedCopy('roster.explainer.body')}</p>
            <p>{guidedCopy('roster.explainer.purpose')}</p>
            <p>{guidedCopy('names.scope.public')}</p>
          </aside>
        ) : null}

        <GuidedFacesPanel
          scenario={scenario}
          state={demo}
          onChoose={handleChoose}
          onContinue={() => {
            handleSelectStep(GUIDED_STEP.DRAFT);
            focusGuidedSection(GUIDED_STEP.DRAFT);
          }}
          onConfirmReplacement={() => {
            commit(confirmGuidedChoiceReplacement(demo, scenario));
            focusGuidedSection(GUIDED_STEP.DRAFT);
          }}
          onCancelReplacement={handleCancelReplacement}
        />

        {scope === 'public' ? <p className="acx-guided-review__explanation">{guidedCopy('draft.context.public')}</p> : null}

        <GuidedDescriptionReview
          scenario={scenario}
          state={demo}
          {...(scope === 'public' ? { recordedOriginLabel: guidedCopy('draft.origin.public') } : {})}
          actions={{
            onEdit: (text) => commit(editGuidedDraft(demo, text)),
            onDraftInput: (text) => {
              pendingDraftRef.current = text;
            },
            onPreview: handlePreview,
            onKeep: () => commit(keepGuidedCurrentAltText(demo)),
            onRetryFixture: () => commit(retryGuidedFixture(demo, scenario)),
            onRestore: (revisionId: string, mode: GuidedRestoreMode) =>
              commit(restoreGuidedRevision(demo, revisionId, mode)),
            onApply: (text) => {
              let next = demo;
              if (text !== (next.draftText ?? '')) {
                next = editGuidedDraft(next, text);
              }
              commit(applyGuidedDraft(next));
            },
            onUndo: () => {
              commit(undoGuidedApplication(demo));
            },
          }}
        />

        <GuidedOutcome
          outcome={demo.outcome}
          scope={scope}
          onReturn={() => {
            handleSelectStep(GUIDED_STEP.DRAFT);
            focusGuidedSection(GUIDED_STEP.DRAFT);
          }}
        />

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
