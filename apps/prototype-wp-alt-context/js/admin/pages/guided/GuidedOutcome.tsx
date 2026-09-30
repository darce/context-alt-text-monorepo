import React from 'react';

import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';
import {
  GUIDED_IMAGE_KEYS,
  GUIDED_OUTCOME,
  type GuidedImageKey,
  type GuidedOutcome as GuidedOutcomeValue,
} from '../../guidedPrototype/state';

export interface GuidedOutcomeSummary {
  imageKey: GuidedImageKey;
  label: string;
  outcome: GuidedOutcomeValue;
  appliedAltText?: string;
}

export type GuidedOutcomeInput = GuidedOutcomeValue | Partial<Record<GuidedImageKey, GuidedOutcomeValue>>;

export interface GuidedOutcomeProps {
  outcome?: GuidedOutcomeInput;
  outcomeReady?: boolean;
  onReturn: () => void;
  scope?: 'public' | 'admin';
  outcomes?: Partial<Record<GuidedImageKey, GuidedOutcomeValue>>;
  summaries?: readonly GuidedOutcomeSummary[];
}

const GUIDED_IMAGE_LABELS: Record<GuidedImageKey, string> = {
  tribeca: 'Tribeca',
  coachella: 'Coachella',
};

const PUBLIC_IMAGE_NAMES: Record<GuidedImageKey, string> = {
  tribeca: 'Tribeca Festival, New York, June 2026',
  coachella: 'Coachella festival photo, 2026',
};

const PUBLIC_PROVENANCE =
  'AltContext suggested these names and descriptions on 9-10 September 2026. Nothing on this page compares faces.';

const outcomeSummaries = (
  outcome: GuidedOutcomeInput | undefined,
  outcomes: Partial<Record<GuidedImageKey, GuidedOutcomeValue>> | undefined,
  summaries: readonly GuidedOutcomeSummary[] | undefined,
): readonly GuidedOutcomeSummary[] => {
  if (summaries !== undefined) {
    return GUIDED_IMAGE_KEYS.flatMap((imageKey) => {
      const summary = summaries.find((candidate) => candidate.imageKey === imageKey);
      return summary === undefined ? [] : [summary];
    });
  }

  const perImage = outcomes ?? (typeof outcome === 'object' && outcome !== null ? outcome : undefined);
  if (perImage !== undefined) {
    return GUIDED_IMAGE_KEYS.map((imageKey) => ({
      imageKey,
      label: GUIDED_IMAGE_LABELS[imageKey],
      outcome: perImage[imageKey] ?? GUIDED_OUTCOME.NOT_FINISHED,
    }));
  }

  return [];
};

export const GuidedOutcome = ({
  outcome,
  outcomeReady,
  onReturn,
  scope = 'admin',
  outcomes,
  summaries,
}: GuidedOutcomeProps): React.JSX.Element | null => {
  const imageSummaries = outcomeSummaries(outcome, outcomes, summaries);
  const singleOutcome = typeof outcome === 'string' ? outcome : undefined;
  const allOutcomes = imageSummaries.length > 0 ? imageSummaries.map((summary) => summary.outcome) : [singleOutcome];
  const bothImagesFinished =
    imageSummaries.length === GUIDED_IMAGE_KEYS.length &&
    imageSummaries.every(
      (summary) => summary.outcome === GUIDED_OUTCOME.APPLIED || summary.outcome === GUIDED_OUTCOME.KEPT,
    );

  if (scope === 'public') {
    if (!(outcomeReady ?? bothImagesFinished) || !bothImagesFinished) {
      return null;
    }

    return (
      <section className="acx-guided-outcome" data-testid="demo-outcome" aria-labelledby="acx-guided-outcome-title">
        <h2 id="acx-guided-outcome-title">{guidedCopy('outcome.title.public')}</h2>
        <ul data-testid="guided-outcome-summaries">
          {imageSummaries.map((summary) => (
            <li key={summary.imageKey} data-image-key={summary.imageKey}>
              {guidedCopy(
                summary.outcome === GUIDED_OUTCOME.APPLIED ? 'outcome.applied.public' : 'outcome.kept.public',
                { photoName: PUBLIC_IMAGE_NAMES[summary.imageKey] },
              )}
            </li>
          ))}
        </ul>
        <p>{guidedCopy('outcome.scope.public')}</p>
        <p>{guidedCopy('outcome.next_batch.public')}</p>
        <p>{PUBLIC_PROVENANCE}</p>
      </section>
    );
  }

  if (outcomeReady === false) {
    return null;
  }

  if (allOutcomes.every((value) => value === undefined || value === GUIDED_OUTCOME.NOT_FINISHED)) {
    return null;
  }

  const applied = allOutcomes.some((value) => value === GUIDED_OUTCOME.APPLIED);
  const publicScope = scope === 'public';

  return (
    <section className="acx-guided-outcome" data-testid="demo-outcome" aria-labelledby="acx-guided-outcome-title">
      <h2 id="acx-guided-outcome-title">{applied ? guidedCopy('outcome.applied') : guidedCopy('outcome.kept')}</h2>
      {applied ? (
        <p>{guidedCopy('apply.success')}</p>
      ) : (
        <p>{guidedCopy(publicScope ? 'outcome.kept_body.public' : 'outcome.kept_body')}</p>
      )}
      {imageSummaries.length > 0 ? (
        <ul data-testid="guided-outcome-summaries">
          {imageSummaries.map((summary) => (
            <li key={summary.imageKey} data-image-key={summary.imageKey}>
              <h3>{summary.label}</h3>
              <p>
                {summary.outcome === GUIDED_OUTCOME.APPLIED
                  ? guidedCopy('outcome.applied')
                  : guidedCopy('outcome.kept')}
              </p>
              {summary.appliedAltText !== undefined ? <p data-applied-text>{summary.appliedAltText}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {publicScope ? (
        <>
          <p>{guidedCopy('outcome.scope.public')}</p>
          <p>{guidedCopy('outcome.next_batch.public')}</p>
        </>
      ) : null}
      <button type="button" className="acx-button acx-button--secondary" onClick={onReturn}>
        {guidedCopy('outcome.return')}
      </button>
    </section>
  );
};

GuidedOutcome.displayName = 'GuidedOutcome';
