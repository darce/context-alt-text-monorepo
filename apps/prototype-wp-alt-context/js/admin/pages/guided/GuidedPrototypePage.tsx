import React, { useMemo, useState } from 'react';

import {
  applyGuidedCandidate,
  confirmGuidedIdentity,
  createGuidedScenario,
  leaveGuidedIdentityUnidentified,
  rejectGuidedCandidate,
  saveGuidedEdit,
  undoGuidedApplication,
  type GuidedScenario,
} from '../../guidedPrototype/state';
import { GuidedPrototypeEntrance } from '../GuidedPrototypeEntrance';
import { GuidedDescriptionReview } from './GuidedDescriptionReview';
import { GuidedPrototypeGuide, type GuidedGuideStep } from './GuidedPrototypeGuide';

const initialScenario = (): GuidedScenario => createGuidedScenario();

export const GuidedPrototypePage = (): React.JSX.Element => {
  const [scenario, setScenario] = useState<GuidedScenario>(initialScenario);
  const [guideOpen, setGuideOpen] = useState(false);
  const [activeStep, setActiveStep] = useState<GuidedGuideStep>('understand');
  const [feedback, setFeedback] = useState('');
  const [sessionState] = useState<'active'>('active');

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

  const updateScenario = (
    operation: (current: GuidedScenario) => GuidedScenario,
    message: string,
    step?: GuidedGuideStep,
  ): void => {
    setScenario((current) => operation(current));
    setFeedback(message);
    if (step) {
      setActiveStep(step);
    }
  };

  const handleSaveEdit = (text: string): void => {
    try {
      updateScenario((current) => saveGuidedEdit(current, text), 'Your edit is ready for review.', 'review');
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'Unable to save this edit.');
    }
  };

  const handleApply = (): void => {
    try {
      updateScenario((current) => applyGuidedCandidate(current), 'Applied to the practice copy.', 'apply');
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'Unable to apply this description.');
    }
  };

  const resetPractice = (): void => {
    setScenario(initialScenario());
    setActiveStep('understand');
    setFeedback('Practice reset. The original applied text is back.');
  };

  return (
    <main className="acx-guided-page" aria-labelledby="acx-guided-page-title">
      <GuidedPrototypeEntrance sessionState={sessionState} onBegin={beginGuide} />
      <GuidedPrototypeGuide
        activeStep={activeStep}
        open={guideOpen}
        onToggle={() => setGuideOpen((current) => !current)}
        onSelect={(step) => {
          setActiveStep(step);
          setFeedback(`Guide moved to ${step}.`);
        }}
        onEnd={() => {
          setGuideOpen(false);
          setFeedback('Guide ended. You can continue with the same practice scenario.');
        }}
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
          <button type="button" className="acx-button acx-button--tertiary" onClick={resetPractice}>
            Reset practice
          </button>
        </header>

        <div className="acx-guided-page__scenario">
          <figure className="acx-guided-page__media-card">
            <div className="acx-guided-page__image-placeholder" role="img" aria-label={scenario.originalMedia.altText}>
              Portrait practice image
            </div>
            <figcaption>
              <strong>Original media</strong>
              <span>{scenario.originalMedia.altText}</span>
            </figcaption>
          </figure>
          <div className="acx-guided-page__provenance">
            <h3>Provenance you can inspect</h3>
            <dl>
              <div>
                <dt>Scenario origin</dt>
                <dd>{scenario.origin}</dd>
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
        </div>

        <p className="acx-guided-page__feedback" role="status" aria-live="polite">
          {feedback}
        </p>

        <GuidedDescriptionReview
          scenario={scenario}
          onConfirmIdentity={() =>
            updateScenario(
              (current) => confirmGuidedIdentity(current),
              'Identity confirmed from the sample record. The description has not been applied.',
              'review',
            )
          }
          onLeaveUnidentified={() =>
            updateScenario(
              (current) => leaveGuidedIdentityUnidentified(current),
              'Identity left unidentified. You can still review a description.',
              'review',
            )
          }
          onSaveEdit={handleSaveEdit}
          onReject={() =>
            updateScenario(
              (current) => rejectGuidedCandidate(current),
              'Draft rejected; the applied text was left alone.',
              'review',
            )
          }
          onApply={handleApply}
          onUndo={() => updateScenario((current) => undoGuidedApplication(current), 'Application undone.', 'review')}
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
