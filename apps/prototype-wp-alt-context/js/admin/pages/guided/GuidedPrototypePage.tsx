import React, { useMemo, useState } from 'react';

import {
  applyGuidedCandidate,
  confirmGuidedIdentity,
  createGuidedScenario,
  GUIDED_SCENARIO_ORIGIN_LABELS,
  leaveGuidedIdentityUnidentified,
  rejectGuidedCandidate,
  saveGuidedEdit,
  undoGuidedApplication,
  type GuidedScenario,
} from '../../guidedPrototype/state';
import { GuidedPrototypeEntrance } from '../GuidedPrototypeEntrance';
import { GuidedDescriptionReview } from './GuidedDescriptionReview';
import {
  focusGuidedSection,
  guidedStepLabel,
  GuidedPrototypeGuide,
  type GuidedGuideStep,
} from './GuidedPrototypeGuide';
import { GuidedResetDialog } from './GuidedResetDialog';
import { GuidedSamplePhoto } from './GuidedSamplePhoto';

const initialScenario = (): GuidedScenario => createGuidedScenario();

export const GuidedPrototypePage = (): React.JSX.Element => {
  const [scenario, setScenario] = useState<GuidedScenario>(initialScenario);
  const [guideOpen, setGuideOpen] = useState(false);
  const [activeStep, setActiveStep] = useState<GuidedGuideStep>('understand');
  const [feedback, setFeedback] = useState('');
  const [resetVersion, setResetVersion] = useState(0);

  const historyLabels = useMemo(
    () =>
      scenario.history.map((event, index) => {
        const labels: Record<typeof event.kind, string> = {
          'identity-confirmed': 'Identity confirmed from the sample record.',
          'identity-unidentified': 'Identity left unidentified.',
          'edit-saved': 'Your description edit was saved for review.',
          rejected: 'Draft rejected; the applied text was left alone.',
          applied: 'Applied to the practice copy.',
          'application-undone': 'Application undone.',
        };
        return { id: `${event.kind}-${index}`, label: labels[event.kind] };
      }),
    [scenario.history],
  );

  const beginGuide = (): void => {
    setGuideOpen(true);
    setActiveStep('understand');
    setFeedback('The guide is open. Start with the image and page context.');
  };

  const handleGuideToggle = (): void => {
    setGuideOpen((current) => !current);
  };

  const handleGuideSelect = (step: GuidedGuideStep): void => {
    setActiveStep(step);
    setFeedback(`Guide moved to: ${guidedStepLabel(step)}.`);
  };

  const handleGuideEnd = (): void => {
    setGuideOpen(false);
    setFeedback('Guide ended. You can continue with the same practice scenario.');
    focusGuidedSection('understand');
  };

  const updateScenario = (
    operation: (current: GuidedScenario) => GuidedScenario,
    message: string,
    step?: GuidedGuideStep,
    announceError = true,
  ): string | undefined => {
    try {
      // Evaluate the operation in the event handler so a domain validation error
      // can be shown in the single page feedback channel rather than escaping a
      // React state updater during render.
      const nextScenario = operation(scenario);
      setScenario(nextScenario);
      setFeedback(message);
      if (step) {
        setActiveStep(step);
      }
      return undefined;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unable to update this practice scenario.';
      setFeedback(announceError ? errorMessage : '');
      return errorMessage;
    }
  };

  const handleSaveEdit = (text: string): string | undefined => {
    return updateScenario(
      (current) => saveGuidedEdit(current, text),
      'Your edit is ready for review.',
      'review',
      false,
    );
  };

  const handleApply = (): void => {
    updateScenario((current) => applyGuidedCandidate(current), 'Applied to the practice copy.', 'apply');
  };

  const resetPractice = (): void => {
    setScenario(initialScenario());
    setResetVersion((current) => current + 1);
    setActiveStep('understand');
    setFeedback('Practice reset. The original applied text is back.');
  };

  const handleConfirmIdentity = (): void => {
    updateScenario(
      (current) => confirmGuidedIdentity(current),
      'Identity confirmed from the sample record. The description has not been applied.',
      'review',
    );
  };

  const handleLeaveUnidentified = (): void => {
    updateScenario(
      (current) => leaveGuidedIdentityUnidentified(current),
      'Identity left unidentified. You can still review a description.',
      'review',
    );
  };

  const handleReject = (): void => {
    updateScenario(
      (current) => rejectGuidedCandidate(current),
      'Draft rejected; the applied text was left alone.',
      'review',
    );
  };

  const handleUndo = (): void => {
    updateScenario((current) => undoGuidedApplication(current), 'Application undone.', 'apply');
    focusGuidedSection('apply');
  };

  return (
    <main className="acx-guided-page" aria-labelledby="acx-guided-entrance-title">
      <GuidedPrototypeEntrance onBegin={beginGuide} />
      <GuidedPrototypeGuide
        activeStep={activeStep}
        open={guideOpen}
        onToggle={handleGuideToggle}
        onSelect={handleGuideSelect}
        onEnd={handleGuideEnd}
      />

      <section className="acx-guided-page__workspace" aria-labelledby="acx-guided-page-title">
        <header className="acx-guided-page__hero">
          <div>
            <p className="acx-guided-page__eyebrow">Saved illustrative scenario · {scenario.scenarioVersion}</p>
            <h2 id="acx-guided-page-title">Practice with page context</h2>
            <p>
              Description quality comes from combining what the image shows, who the page says is present, and your
              final review.
            </p>
          </div>
          <GuidedResetDialog onConfirm={resetPractice} />
        </header>

        <section
          id="guided-section-understand"
          className="acx-guided-page__scenario"
          aria-label="Image and page context"
          tabIndex={-1}
        >
          <GuidedSamplePhoto mediaAltText={scenario.originalMedia.altText} credit={scenario.sourceRecord.credit} />
          <div className="acx-guided-page__provenance">
            <h3>Provenance you can inspect</h3>
            <dl>
              <div>
                <dt>Scenario origin</dt>
                <dd>{GUIDED_SCENARIO_ORIGIN_LABELS[scenario.origin]}</dd>
              </div>
              <div>
                <dt>Page</dt>
                <dd>{scenario.pageContext.title}</dd>
              </div>
              <div>
                <dt>Sample record</dt>
                <dd>
                  {scenario.sourceRecord.name} · {scenario.sourceRecord.credit}
                </dd>
              </div>
            </dl>
          </div>
        </section>

        <p className="acx-guided-page__feedback" role="status" aria-live="polite">
          {feedback}
        </p>

        <GuidedDescriptionReview
          scenario={scenario}
          resetVersion={resetVersion}
          onConfirmIdentity={handleConfirmIdentity}
          onLeaveUnidentified={handleLeaveUnidentified}
          onSaveEdit={handleSaveEdit}
          onReject={handleReject}
          onApply={handleApply}
          onUndo={handleUndo}
        />

        <section className="acx-guided-history" aria-labelledby="acx-guided-history-title">
          <div>
            <p className="acx-guided-page__eyebrow">Recovery and provenance</p>
            <h2 id="acx-guided-history-title">Decision history</h2>
          </div>
          {historyLabels.length === 0 ? (
            <p>No decisions recorded yet. Your next action will appear here.</p>
          ) : (
            <ol>
              {historyLabels.map((event) => (
                <li key={event.id}>{event.label}</li>
              ))}
            </ol>
          )}
        </section>
      </section>
    </main>
  );
};

GuidedPrototypePage.displayName = 'GuidedPrototypePage';
