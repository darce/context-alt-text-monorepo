import React from 'react';

import { CASE_STUDY_URL, guidedCopy } from '../guidedPrototype/publicGuideCopy';

const PRODUCT_HOME_URL = 'https://altcontext.com/';

export interface GuidedPrototypeEntranceProps {
  onBegin: () => void;
  scope?: 'public' | 'admin';
  escapeHref?: string;
}

const NEW_WINDOW_HINT = ' (opens in a new window)';

const ExternalGuideLink = ({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: React.ReactNode;
}): React.JSX.Element => (
  <a className={className} href={href} target="_blank" rel="noreferrer">
    {children}
    <span className="screen-reader-text">{NEW_WINDOW_HINT}</span>
  </a>
);

export const GuidedPrototypeEntrance = ({
  onBegin,
  scope = 'admin',
  escapeHref = '/',
}: GuidedPrototypeEntranceProps): React.JSX.Element => {
  if (scope === 'public') {
    return (
      <section className="acx-guided-entrance" aria-labelledby="acx-guided-entrance-title">
        <nav className="acx-guided-entrance__escape" aria-label={guidedCopy('nav.leave')}>
          <ExternalGuideLink href={PRODUCT_HOME_URL}>{guidedCopy('nav.home')}</ExternalGuideLink>
          <ExternalGuideLink href={CASE_STUDY_URL}>{guidedCopy('nav.case_study')}</ExternalGuideLink>
        </nav>
        <h1 id="acx-guided-entrance-title">{guidedCopy('entry.title.public')}</h1>
        <p className="acx-guided-entrance__intro">{guidedCopy('entry.intro.public')}</p>
        <p className="acx-guided-entrance__scope" data-testid="guided-scope">
          {guidedCopy('scope.public')}
        </p>
        <div className="acx-guided-entrance__actions">
          <button type="button" className="acx-button acx-button--primary" onClick={onBegin}>
            {guidedCopy('page.start')}
          </button>
          <ExternalGuideLink className="acx-button acx-button--secondary" href={CASE_STUDY_URL}>
            {guidedCopy('entry.read_case_study')}
          </ExternalGuideLink>
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
        <ExternalGuideLink className="acx-guided-entrance__case-study" href={CASE_STUDY_URL}>
          {guidedCopy('page.case_study')}
        </ExternalGuideLink>
      </p>
    </section>
  );
};

GuidedPrototypeEntrance.displayName = 'GuidedPrototypeEntrance';
