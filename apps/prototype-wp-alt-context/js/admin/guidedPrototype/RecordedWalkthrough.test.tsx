import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { GuidedPrototypePage } from '../pages/guided/GuidedPrototypePage';
import { CASE_STUDY_URL, guidedCopy as publicGuidedCopy } from './publicGuideCopy';
import { RecordedWalkthrough } from './RecordedWalkthrough';

const guidedCopy = publicGuidedCopy;

const START_DEMO = guidedCopy('entry.start.public');
const READ_CASE_STUDY = guidedCopy('entry.read_case_study');
const CANONICAL_CASE_STUDY_URL = 'https://darce.xyz/projects/altcontext/';
const opensInNewWindow = (label: string): string => `${label} (opens in a new window)`;

describe('RecordedWalkthrough extraction', () => {
  it('renders the admin walkthrough with its stepper', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByTestId('guided-demo-root')).toBeInTheDocument();
    expect(screen.getByTestId('guided-demo-root').tagName).toBe('MAIN');
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByTestId('guided-demo-stepper')).toBeInTheDocument();
  });

  it('renders the live panel through the admin composition slot', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByTestId('guided-live')).toBeInTheDocument();
  });

  it('keeps GuidedPrototypePage as the admin composition with the live panel', () => {
    render(<GuidedPrototypePage />);

    expect(screen.getByTestId('guided-demo-root')).toBeInTheDocument();
    expect(screen.getByTestId('guided-live')).toBeInTheDocument();
  });
});

describe('RecordedWalkthrough public scope', () => {
  it('keeps implementation notes and the action log out of the public walkthrough', () => {
    const { container } = render(<RecordedWalkthrough scope="public" />);
    expect(container.querySelector('.acx-guided-notes')).toBeNull();
    expect(container.querySelector('.acx-guided-history')).toBeNull();
  });

  it('opens every roster reference before a visitor makes a name choice', async () => {
    const user = userEvent.setup();
    const { container } = render(<RecordedWalkthrough scope="public" />);
    for (const photoKey of ['tribeca', 'coachella']) {
      const faces = container.querySelector(`[data-testid="guided-faces-${photoKey}"]`);
      expect(faces).not.toBeNull();
      const cards = Array.from(faces?.querySelectorAll('.acx-guided-face__card') ?? []);
      expect(cards).toHaveLength(2);
      for (const card of cards) {
        const faceCard = card as HTMLElement;
        const name = within(faceCard).getByRole('heading', { level: 5 }).textContent ?? '';
        await user.click(within(faceCard).getByRole('button', { name: publicGuidedCopy('names.compare.public') }));
        const dialog = screen.getByRole('dialog', {
          name: publicGuidedCopy('lightbox.title.public', { name }),
        });
        const gallery = within(dialog).getByRole('list', {
          name: publicGuidedCopy('lightbox.references.public', { name }),
        });
        expect(gallery.querySelectorAll('img').length).toBeGreaterThanOrEqual(2);
        await user.click(within(dialog).getByRole('button', { name: publicGuidedCopy('lightbox.close.public') }));
      }
    }
  });

  it('keeps each public photo review beside its name choices and provenance after the photo list', () => {
    const { container } = render(<RecordedWalkthrough scope="public" />);
    const scenario = container.querySelector('.acx-guided-page__scenario');
    const context = scenario?.querySelector('.acx-guided-page__context');
    const mediaList = scenario?.querySelector('.acx-guided-page__media-list');
    const footer = scenario?.querySelector('.acx-guided-page__provenance-footer');
    const review = container.querySelector('.acx-guided-review__image-card');

    expect(scenario).not.toBeNull();
    expect(scenario?.firstElementChild).toBe(context);
    expect(context?.children).toHaveLength(1);
    expect(context?.querySelector('p')).toHaveTextContent(guidedCopy('context.purpose'));
    expect(context?.querySelector('details, button')).toBeNull();
    expect(mediaList).not.toBeNull();
    expect(footer).not.toBeNull();
    expect(scenario?.querySelector('button.acx-button--primary')).toBeNull();
    expect(mediaList?.compareDocumentPosition(footer ?? mediaList)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(review).not.toBeNull();

    for (const photoKey of ['tribeca', 'coachella']) {
      const faces = container.querySelector(`[data-testid="guided-faces-${photoKey}"]`);
      const photoStep = container.querySelector(`[data-testid="guided-photo-step-${photoKey}"]`);
      const reviewCard = container.querySelector(`[data-testid="guided-description-review-${photoKey}"]`);
      const photo = container.querySelector(`[data-testid="guided-photo-${photoKey}"]`);
      expect(faces?.querySelectorAll('section.acx-guided-face__card')).toHaveLength(2);
      expect(faces?.querySelectorAll(`input[name="guided-name-${photoKey}-left"]`)).toHaveLength(2);
      expect(faces?.querySelectorAll(`input[name="guided-name-${photoKey}-right"]`)).toHaveLength(2);
      expect(photoStep).toContainElement(reviewCard as HTMLElement);
      expect(faces).not.toContainElement(reviewCard as HTMLElement);
      expect(reviewCard?.parentElement).toBe(photoStep);
      expect(photo?.compareDocumentPosition(reviewCard as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it('exports the case-study URL from copy', () => {
    expect(CASE_STUDY_URL).toBe(CANONICAL_CASE_STUDY_URL);
    expect(CASE_STUDY_URL).not.toContain('github.io');
  });

  it('renders public scope copy first, the escape hatch, and the two entry actions', () => {
    render(<RecordedWalkthrough scope="public" />);

    const scope = screen.getByTestId('guided-scope');
    expect(scope.tagName).toBe('P');
    expect(scope).toHaveTextContent(guidedCopy('scope.public'));
    expect(screen.getByRole('heading', { level: 1, name: guidedCopy('entry.title.public') })).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('entry.intro.public'))).toBeInTheDocument();

    const entrance = document.querySelector('.acx-guided-entrance');
    expect(entrance?.querySelector('h1')).toHaveTextContent(guidedCopy('entry.title.public'));

    const escape = screen.getByRole('navigation', { name: 'Leave the walkthrough' });
    expect(escape.querySelector('a[href="https://altcontext.com/"]')).not.toBeNull();
    expect(escape.querySelector(`a[href="${CASE_STUDY_URL}"]`)).not.toBeNull();

    expect(screen.getByRole('button', { name: START_DEMO })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: opensInNewWindow(READ_CASE_STUDY) })).toHaveAttribute(
      'href',
      CASE_STUDY_URL,
    );
  });

  it('gives every public entry action a distinct destination', () => {
    render(<RecordedWalkthrough scope="public" />);

    const read = screen.getByRole('link', { name: opensInNewWindow(READ_CASE_STUDY) });
    const caseStudyNav = screen.getByRole('link', { name: opensInNewWindow(guidedCopy('nav.case_study')) });
    const start = screen.getByRole('button', { name: START_DEMO });

    const actionLinks = Array.from(document.querySelectorAll('.acx-guided-entrance__actions a'));
    const actionHrefs = actionLinks.map((link) => link.getAttribute('href'));
    expect(actionHrefs).toEqual([CASE_STUDY_URL]);
    expect(new Set(actionHrefs).size).toBe(actionHrefs.length);

    expect(read).toHaveAttribute('href', CASE_STUDY_URL);
    expect(caseStudyNav).toHaveAttribute('href', CASE_STUDY_URL);
    expect(start).not.toHaveAttribute('href');
  });

  it('opens public case-study exits and Home in a new tab', () => {
    render(<RecordedWalkthrough scope="public" />);

    const read = screen.getByRole('link', { name: opensInNewWindow(READ_CASE_STUDY) });
    const escape = screen.getByRole('navigation', { name: guidedCopy('nav.leave') });
    const caseStudyNav = within(escape).getByRole('link', {
      name: opensInNewWindow(guidedCopy('nav.case_study')),
    });
    const home = within(escape).getByRole('link', { name: opensInNewWindow(guidedCopy('nav.home')) });

    for (const link of [read, caseStudyNav]) {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link.getAttribute('rel') ?? '').toContain('noreferrer');
      expect(link).toHaveAccessibleName(/opens in a new window/i);
    }

    expect(home).toHaveAttribute('href', 'https://altcontext.com/');
    expect(home).toHaveAttribute('target', '_blank');
    expect(home.getAttribute('rel') ?? '').toContain('noreferrer');
    expect(home).toHaveAccessibleName(opensInNewWindow(guidedCopy('nav.home')));
  });

  it('reaches Start, then Read by Tab in that order', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    const start = screen.getByRole('button', { name: START_DEMO });
    start.focus();
    expect(document.activeElement).toBe(start);

    await user.tab();
    expect(document.activeElement).toHaveAccessibleName(opensInNewWindow(READ_CASE_STUDY));
  });

  it('keeps admin entrance copy and the existing case-study link', () => {
    render(<GuidedPrototypePage />);

    expect(screen.queryByTestId('guided-scope')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: guidedCopy('entry.title.public') })).not.toBeInTheDocument();
    expect(screen.getByText(guidedCopy('page.scope'))).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('page.live_scope'))).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Leave the walkthrough' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: READ_CASE_STUDY })).not.toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: new RegExp(`${guidedCopy('page.case_study')}.*opens in a new window`, 'i') }),
    ).toHaveAttribute('href', CANONICAL_CASE_STUDY_URL);
    expect(CASE_STUDY_URL).toBe(CANONICAL_CASE_STUDY_URL);
  });
});

describe('RecordedWalkthrough design notes', () => {
  it('hides live-generation copy on the public surface and keeps it for admin', () => {
    const { unmount } = render(<RecordedWalkthrough scope="public" />);
    expect(document.body.textContent ?? '').not.toContain('Live generation');
    unmount();

    render(<GuidedPrototypePage />);
    expect(document.body.textContent ?? '').toContain('Live generation');
  });
});
