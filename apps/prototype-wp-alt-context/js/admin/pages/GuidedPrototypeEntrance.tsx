import React from 'react';

import { CASE_STUDY_URL, guidedCopy } from '../guidedPrototype/publicGuideCopy';

export interface GuidedPrototypeEntranceProps {
  onBegin: () => void;
  scope?: 'public' | 'admin';
  escapeHref?: string;
}

export const GuidedPrototypeEntrance = ({
  onBegin,
  scope = 'admin',
  escapeHref = '/',
}: GuidedPrototypeEntranceProps): React.JSX.Element => {
  if (scope === 'public') {
    return (
      <section className="acx-guided-entrance" aria-labelledby="acx-guided-entrance-title">
        <nav className="acx-guided-entrance__escape" aria-label={guidedCopy('nav.leave')}>
          <a href={escapeHref}>{guidedCopy('nav.home')}</a>
          <a href={CASE_STUDY_URL}>{guidedCopy('nav.case_study')}</a>
        </nav>
        <p className="acx-guided-entrance__scope" data-testid="guided-scope">
          {guidedCopy('scope.public')}
        </p>
        <h1 id="acx-guided-entrance-title">{guidedCopy('page.title')}</h1>
        <div className="acx-guided-entrance__actions">
          <button type="button" className="acx-button acx-button--primary" onClick={onBegin}>
            {guidedCopy('page.start')}
          </button>
          <a className="acx-button acx-button--secondary" href={CASE_STUDY_URL}>
            {guidedCopy('entry.watch')}
          </a>
          <a className="acx-button acx-button--secondary" href={CASE_STUDY_URL}>
            {guidedCopy('entry.read_case_study')}
          </a>
        </div>
      </section>
    );
  }

  return (
    <section className="acx-guided-entrance" aria-labelledby="acx-guided-entrance-title">
      <p className="acx-guided-entrance__eyebrow">{guidedCopy('page.eyebrow')}</p>
      <h1 id="acx-guided-entrance-title">{guidedCopy('page.title')}</h1>
      <p className="acx-guided-entrance__intro">{guidedCopy('page.intro')}</p>
      <p className="acx-guided-entrance__scope">{guidedCopy('page.scope')}</p>
      <p className="acx-guided-entrance__live-scope">{guidedCopy('page.live_scope')}</p>

      <button type="button" className="acx-button acx-button--primary" onClick={onBegin}>
        {guidedCopy('page.start')}
      </button>

      <p className="acx-guided-entrance__boundary">
        <a className="acx-guided-entrance__case-study" href={CASE_STUDY_URL} target="_blank" rel="noreferrer">
          {guidedCopy('page.case_study')}
          <span className="screen-reader-text"> (opens in a new window)</span>
        </a>
      </p>
    </section>
  );
};

GuidedPrototypeEntrance.displayName = 'GuidedPrototypeEntrance';
