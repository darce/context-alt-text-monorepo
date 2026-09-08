import React, { useMemo, useRef, useState } from 'react';

import { getGuidedLiveMediaId } from '../../api/config';
import { ErrorBoundary } from '../../../components/ErrorBoundary';
import { guidedCopy } from '../../guidedPrototype/copy';
import {
  GUIDED_STEP,
  guidedStepIndex,
  applyGuidedDraft,
  cancelGuidedChoiceReplacement,
  chooseGuidedName,
  confirmGuidedChoiceReplacement,
  createGuidedDemoState,
  createGuidedScenario,
  editGuidedDraft,
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
  type GuidedStep,
} from '../../guidedPrototype/state';
import { GuidedPrototypeEntrance } from '../GuidedPrototypeEntrance';
import { GuidedDesignNotes } from './GuidedDesignNotes';
import { GuidedDescriptionReview } from './GuidedDescriptionReview';
import { GuidedFacesPanel } from './GuidedFacesPanel';
import { GuidedLiveDescriptionPanel } from './GuidedLiveDescriptionPanel';
import { GuidedOutcome } from './GuidedOutcome';
import { focusGuidedSection, guidedStepLabel, GuidedPrototypeGuide } from './GuidedPrototypeGuide';
import { GuidedResetDialog } from './GuidedResetDialog';
import { GuidedSamplePhoto } from './GuidedSamplePhoto';

const lastSummary = (state: GuidedDemoState): string => state.actionHistory.at(-1)?.summary ?? '';

export const GuidedPrototypePage = (): React.JSX.Element => {
  const scenario = useMemo(() => createGuidedScenario(), []);
  const [demo, setDemo] = useState(createGuidedDemoState);
  const [guideOpen, setGuideOpen] = useState(true);
  const [feedback, setFeedback] = useState('');
  const [resetVersion, setResetVersion] = useState(0);
  const [liveWaiting, setLiveWaiting] = useState(false);
  const choiceOriginRef = useRef<HTMLInputElement | null>(null);

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
    commit(chooseGuidedName(demo, scenario, position, choice));
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
    setDemo(resetGuidedDemoState(demo));
    setResetVersion((current) => current + 1);
    setFeedback(guidedCopy('reset.status'));
  };

  return (
    <main className="acx-guided-page" aria-labelledby="acx-guided-entrance-title" data-testid="guided-demo-root">
      <GuidedPrototypeEntrance onBegin={handleBegin} />
      <GuidedPrototypeGuide
        activeStep={demo.activeStep}
        open={guideOpen}
        onToggle={() => setGuideOpen((current) => !current)}
        onSelect={handleSelectStep}
      />

      <section className="acx-guided-page__workspace" aria-labelledby="acx-guided-page-title">
        <header className="acx-guided-page__hero">
          <h2 id="acx-guided-page-title">{guidedCopy('step.context')}</h2>
          <GuidedResetDialog liveWaiting={liveWaiting} onConfirm={handleReset} />
        </header>

        <section id="guided-section-understand" className="acx-guided-page__scenario" tabIndex={-1}>
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
        </section>

        <p className="acx-guided-page__feedback" data-testid="guided-page-feedback" role="status" aria-live="polite">
          {feedback ? (
            <span
              className="acx-guided-page__feedback-icon"
              aria-hidden="true"
              data-testid="guided-page-feedback-icon"
            />
          ) : null}
          {feedback}
        </p>

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

        <GuidedDescriptionReview
          scenario={scenario}
          state={demo}
          actions={{
            onEdit: (text) => commit(editGuidedDraft(demo, text)),
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
          onReturn={() => {
            handleSelectStep(GUIDED_STEP.DRAFT);
            focusGuidedSection(GUIDED_STEP.DRAFT);
          }}
        />

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

        <GuidedDesignNotes />

        <ErrorBoundary
          fallback={
            <p className="acx-guided-live__fallback" role="alert">
              {guidedCopy('live.failed')}
            </p>
          }
        >
          <GuidedLiveDescriptionPanel
            key={resetVersion}
            mediaId={getGuidedLiveMediaId()}
            onWaitingChange={setLiveWaiting}
          />
        </ErrorBoundary>
      </section>
    </main>
  );
};

GuidedPrototypePage.displayName = 'GuidedPrototypePage';
