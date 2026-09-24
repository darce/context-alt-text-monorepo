import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';

import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GuidedPrototypeEntrance } from '../../admin/pages/GuidedPrototypeEntrance';
import { GuidedPrototypePage } from '../../admin/pages/guided/GuidedPrototypePage';
import { CASE_STUDY_URL, guidedCopy as publicGuidedCopy } from '../../admin/guidedPrototype/publicGuideCopy';
import { RecordedWalkthrough } from '../../admin/guidedPrototype/RecordedWalkthrough';
import { createGuidedScenario, GUIDED_MATCH_STRENGTH, formatGuidedSimilarity } from '../../admin/guidedPrototype/state';

const SEED_ALT_TEXT =
  'A man in a black suit and a woman in a white dress pose together, smiling, in front of a Tribeca Festival step-and-repeat backdrop.';
const PUBLIC_HOME_URL = 'https://altcontext.com/';
const guidedCopy = publicGuidedCopy;

const PUBLIC_IMAGE_KEYS = ['tribeca', 'coachella'] as const;
type PublicImageKey = (typeof PUBLIC_IMAGE_KEYS)[number];

const choose = (position: 'left' | 'right', option: 'include' | 'omit', imageKey: PublicImageKey = 'tribeca'): void => {
  const photo = screen.getByTestId(`guided-photo-${imageKey}`);
  const fieldset = within(photo).getByTestId(`name-choice-${imageKey}-${position}`);
  const name =
    option === 'include'
      ? publicGuidedCopy('names.use.public', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : publicGuidedCopy('names.omit.public');
  fireEvent.click(within(fieldset).getByRole('radio', { name }));
};

const chooseBothImages = (position: 'left' | 'right', option: 'include' | 'omit'): void => {
  PUBLIC_IMAGE_KEYS.forEach((imageKey) => choose(position, option, imageKey));
};

const sampleImage = (imageKey: PublicImageKey): HTMLImageElement => {
  const image = screen.getByTestId(`guided-photo-${imageKey}`).querySelector('img.acx-guided-page__image');
  if (!(image instanceof HTMLImageElement)) {
    throw new Error(`Missing sample photo image for ${imageKey}.`);
  }
  return image;
};

const publicEditor = (imageKey: PublicImageKey): HTMLElement =>
  within(screen.getByTestId(`guided-draft-field-${imageKey}`)).getByRole('textbox', {
    name: guidedCopy('draft.field_label.public'),
  });

const SKIP_IMPORT_EXT = new Set([
  '.css',
  '.scss',
  '.jpg',
  '.jpeg',
  '.png',
  '.gif',
  '.svg',
  '.webp',
  '.json',
  '.woff',
  '.woff2',
]);

interface ImportSpecifier {
  spec: string;
  typeOnly: boolean;
}

const importSpecifiers = (source: string): ImportSpecifier[] => {
  const specs: ImportSpecifier[] = [];
  const pattern = /(?:from|import)\s+['"]([^'"]+)['"]/g;
  for (const match of source.matchAll(pattern)) {
    const spec = match[1];
    const start = match.index ?? 0;
    const lineStart = source.lastIndexOf('\n', start - 1) + 1;
    const prefix = source.slice(lineStart, start);
    specs.push({ spec, typeOnly: /^\s*(?:import|export)\s+type\b/.test(prefix) });
  }
  return specs;
};

const resolveRelativeImport = (fromFile: string, spec: string): string | null => {
  if (!spec.startsWith('.')) {
    return null;
  }
  if (SKIP_IMPORT_EXT.has(extname(spec))) {
    return null;
  }
  const base = resolve(dirname(fromFile), spec);
  const candidates = [base, `${base}.ts`, `${base}.tsx`, join(base, 'index.ts'), join(base, 'index.tsx')];
  for (const candidate of candidates) {
    if (existsSync(candidate) && statSync(candidate).isFile()) {
      return candidate;
    }
  }
  return null;
};

const FORBIDDEN_IMPORT = /\/api\/|GuidedLiveDescriptionPanel|useGuidedLiveDescription/;
const MAX_PUBLIC_GRAPH_FILES = 256;

const collectImportGraph = (entry: string, maxFiles: number = MAX_PUBLIC_GRAPH_FILES): string[] => {
  const seen = new Set<string>();
  const queue = [entry];
  const unresolved: string[] = [];

  while (queue.length > 0) {
    const file = queue.pop();
    if (file === undefined || seen.has(file)) {
      continue;
    }
    seen.add(file);
    if (seen.size > maxFiles) {
      throw new Error(`public import graph exceeded ${maxFiles} files (unbounded walk)`);
    }
    for (const { spec, typeOnly } of importSpecifiers(readFileSync(file, 'utf8'))) {
      if (typeOnly || !spec.startsWith('.')) {
        continue;
      }
      if (SKIP_IMPORT_EXT.has(extname(spec))) {
        continue;
      }
      const resolved = resolveRelativeImport(file, spec);
      if (resolved === null) {
        unresolved.push(`${file} -> ${spec}`);
        continue;
      }
      if (!seen.has(resolved)) {
        queue.push(resolved);
      }
    }
  }

  expect(unresolved, 'unresolved relative imports in the public graph').toEqual([]);
  return [...seen];
};

const forbiddenImportHits = (files: string[]): string[] => {
  const hits: string[] = [];
  for (const file of files) {
    for (const { spec, typeOnly } of importSpecifiers(readFileSync(file, 'utf8'))) {
      if (typeOnly) {
        continue;
      }
      if (FORBIDDEN_IMPORT.test(spec)) {
        hits.push(`${file} imports ${spec}`);
      }
    }
  }
  return hits;
};

describe('public recorded walkthrough boundary', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;
  let xhrOpen: ReturnType<typeof vi.spyOn>;
  let xhrSend: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      throw new Error('public guide must not call fetch');
    });
    xhrOpen = vi.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(() => {
      throw new Error('public guide must not open XHR');
    });
    xhrSend = vi.spyOn(XMLHttpRequest.prototype, 'send').mockImplementation(() => {
      throw new Error('public guide must not send XHR');
    });
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    xhrOpen.mockRestore();
    xhrSend.mockRestore();
  });

  it('renders the public scope text, entry actions, and escape hatch', () => {
    render(<RecordedWalkthrough scope="public" />);

    expect(screen.getByTestId('guided-scope')).toHaveTextContent(guidedCopy('scope.public'));
    expect(screen.getByRole('heading', { level: 1, name: guidedCopy('entry.title.public') })).toBeInTheDocument();
    expect(screen.getByText(guidedCopy('entry.intro.public'))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: guidedCopy('entry.start.public') })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: `${guidedCopy('entry.read_case_study')} (opens in a new window)` }),
    ).toHaveAttribute('href', CASE_STUDY_URL);

    const hero = screen.getByRole('region', { name: guidedCopy('entry.title.public') });
    const action = within(hero).getByRole('button', { name: guidedCopy('entry.start.public') });
    const planTitle = within(hero).getByRole('heading', { level: 2, name: guidedCopy('steps.title.public') });
    const plan = within(hero).getByRole('list');
    expect(action.compareDocumentPosition(planTitle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(plan).toHaveClass('acx-guided-entrance__plan-list');
    expect(within(plan).getAllByRole('listitem')).toHaveLength(3);
    expect(
      within(plan)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual([
      guidedCopy('steps.names.public').replace(/^\d+\.\s*/, ''),
      guidedCopy('steps.description.public').replace(/^\d+\.\s*/, ''),
      guidedCopy('steps.use.public').replace(/^\d+\.\s*/, ''),
    ]);

    const escape = screen.getByRole('navigation', { name: guidedCopy('nav.leave') });
    const home = within(escape).getByRole('link', {
      name: `${guidedCopy('nav.home')} (opens in a new window)`,
    });
    const escapeLinks = within(escape).getAllByRole('link');
    expect(escapeLinks).toHaveLength(2);
    expect(escapeLinks.map((link) => link.getAttribute('href'))).toEqual([PUBLIC_HOME_URL, CASE_STUDY_URL]);
    expect(escapeLinks.filter((link) => link.getAttribute('href') === PUBLIC_HOME_URL)).toHaveLength(1);
    escapeLinks.forEach((link) => {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noreferrer');
    });
    expect(home).toHaveAttribute('href', PUBLIC_HOME_URL);
    expect(home).toHaveAttribute('target', '_blank');
    expect(home).toHaveAttribute('rel', 'noreferrer');
    expect(
      within(escape).getByRole('link', { name: `${guidedCopy('nav.case_study')} (opens in a new window)` }),
    ).toHaveAttribute('href', CASE_STUDY_URL);
    expect(screen.queryByTestId('guided-live')).not.toBeInTheDocument();
  });

  it('lets the public start action focus the first name question', async () => {
    const user = userEvent.setup();
    const onBegin = vi.fn();
    let firstNameQuestion: HTMLInputElement | null = null;
    const onFocusFirstNameQuestion = vi.fn(() => firstNameQuestion?.focus());

    render(
      <>
        <GuidedPrototypeEntrance onBegin={onBegin} onFocusFirstNameQuestion={onFocusFirstNameQuestion} scope="public" />
        <input
          ref={(element) => {
            firstNameQuestion = element;
          }}
          aria-label="First name question"
        />
      </>,
    );

    await user.click(screen.getByRole('button', { name: guidedCopy('entry.start.public') }));

    expect(onBegin).toHaveBeenCalledOnce();
    expect(onFocusFirstNameQuestion).toHaveBeenCalledOnce();
    expect(document.activeElement).toBe(firstNameQuestion);
  });

  it('keeps each public photo in a zero state until its name questions are answered', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    expect(screen.queryByTestId('guided-demo-stepper')).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 2, name: publicGuidedCopy('photos.title.public') }),
    ).toBeInTheDocument();
    const firstNameQuestion = within(screen.getByTestId('guided-photo-tribeca')).getByRole('radio', {
      name: publicGuidedCopy('names.use.public', { name: 'Justin Trudeau' }),
    });
    await user.click(screen.getByRole('button', { name: publicGuidedCopy('entry.start.public') }));
    expect(document.activeElement).toBe(firstNameQuestion);

    for (const imageKey of PUBLIC_IMAGE_KEYS) {
      const review = screen.getByTestId(`guided-description-review-${imageKey}`);
      expect(review).toHaveTextContent(publicGuidedCopy('choices.help.public'));
      expect(within(review).queryByRole('textbox')).not.toBeInTheDocument();
      expect(screen.queryByTestId(`demo-apply-${imageKey}`)).not.toBeInTheDocument();
      expect(screen.queryByTestId(`demo-undo-${imageKey}`)).not.toBeInTheDocument();
      expect(screen.queryByTestId(`guided-image-status-${imageKey}`)).not.toBeInTheDocument();
    }

    choose('left', 'include');
    expect(
      within(screen.getByTestId('guided-description-review-tribeca')).queryByRole('textbox'),
    ).not.toBeInTheDocument();
    choose('right', 'omit');
    expect(publicEditor('tribeca')).toBeInTheDocument();
    expect(
      within(screen.getByTestId('guided-description-review-coachella')).queryByRole('textbox'),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId('demo-apply-coachella')).not.toBeInTheDocument();

    choose('left', 'include', 'coachella');
    expect(
      within(screen.getByTestId('guided-description-review-coachella')).queryByRole('textbox'),
    ).not.toBeInTheDocument();
    choose('right', 'omit', 'coachella');
    expect(publicEditor('coachella')).toBeInTheDocument();
    expect(screen.getByTestId('demo-apply-tribeca')).toBeEnabled();
    expect(screen.getByTestId('demo-apply-coachella')).toBeEnabled();
  });

  it('places each public description review after its photo content', () => {
    render(<RecordedWalkthrough scope="public" />);
    chooseBothImages('left', 'include');
    chooseBothImages('right', 'include');

    const mediaList = document.querySelector('.acx-guided-page__media-list');
    const footer = document.querySelector('.acx-guided-page__provenance-footer');
    expect(mediaList).not.toBeNull();
    expect(footer).not.toBeNull();

    for (const imageKey of PUBLIC_IMAGE_KEYS) {
      const photoStep = screen.getByTestId(`guided-photo-step-${imageKey}`);
      const faces = screen.getByTestId(`guided-faces-${imageKey}`);
      const photo = screen.getByTestId(`guided-photo-${imageKey}`);
      const review = screen.getByTestId(`guided-description-review-${imageKey}`);
      expect(photoStep).toContainElement(review);
      expect(faces).not.toContainElement(review);
      expect(review.parentElement).toBe(photoStep);
      expect(photo.compareDocumentPosition(review) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(review).toContainElement(publicEditor(imageKey));
      expect(screen.queryByTestId(`guided-description-step-${imageKey}`)).not.toBeInTheDocument();
    }

    const renderedIds = Array.from(document.querySelectorAll('[id]'), (element) => element.id);
    expect(new Set(renderedIds).size).toBe(renderedIds.length);

    expect(mediaList?.compareDocumentPosition(footer as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows scored match strength while keeping the cluster anchor score hidden', () => {
    const { container } = render(<RecordedWalkthrough scope="public" />);
    const scenario = createGuidedScenario();
    const strongSimilarity = scenario.faces.find((face) => face.strength === GUIDED_MATCH_STRENGTH.STRONG)?.similarity;
    const weakSimilarity = scenario.faces.find((face) => face.strength === GUIDED_MATCH_STRENGTH.WEAK)?.similarity;
    if (
      strongSimilarity === undefined ||
      strongSimilarity === null ||
      weakSimilarity === undefined ||
      weakSimilarity === null
    ) {
      throw new Error('The recorded scenario must include scored strong and weak matches.');
    }
    const evidence = Array.from(container.querySelectorAll('.acx-guided-face__matches'))
      .map((match) => match.textContent ?? '')
      .join(' ');

    expect(evidence).toContain(
      publicGuidedCopy('names.strong.public', { similarity: formatGuidedSimilarity(strongSimilarity) }),
    );
    expect(evidence).toContain(
      publicGuidedCopy('names.weak.public', { similarity: formatGuidedSimilarity(weakSimilarity) }),
    );
    expect(evidence).toContain(publicGuidedCopy('names.no_score.public'));
    const cards = Array.from(container.querySelectorAll('.acx-guided-face__card'));
    expect(cards.every((card) => !/100(?:\.0)?%/.test(card.textContent ?? ''))).toBe(true);
  });

  it('keeps public headings and editor labels scoped to both source images', () => {
    render(<RecordedWalkthrough scope="public" />);

    expect(screen.getByText(guidedCopy('entry.eyebrow.public'))).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: guidedCopy('entry.title.public') })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 2, name: publicGuidedCopy('photos.title.public') }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: guidedCopy('step.review.public') })).not.toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 4, name: guidedCopy('names.heading.public') })).toHaveLength(2);
    for (const [index, imageKey] of PUBLIC_IMAGE_KEYS.entries()) {
      expect(
        within(screen.getByTestId(`guided-photo-step-${imageKey}`)).getByRole('heading', {
          level: 3,
          name: guidedCopy('photo.count.public', { photoNumber: index + 1 }),
        }),
      ).toBeInTheDocument();
    }
    expect(screen.getAllByText(publicGuidedCopy('comparison.title.public'), { selector: 'summary' })).toHaveLength(2);
    expect(
      screen.queryByRole('heading', { name: guidedCopy('context.photo.altcontext_title') }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: guidedCopy('context.photo.alttextai_title') }),
    ).not.toBeInTheDocument();

    chooseBothImages('left', 'include');
    chooseBothImages('right', 'include');
    for (const imageKey of PUBLIC_IMAGE_KEYS) {
      const review = screen.getByTestId(`guided-description-review-${imageKey}`);
      expect(
        within(review).getAllByRole('heading', {
          level: 4,
          name: guidedCopy('step.review.public'),
        }),
      ).toHaveLength(1);
      expect(within(review).getByRole('textbox', { name: guidedCopy('draft.field_label.public') })).toBeInTheDocument();
      expect(within(review).queryByRole('textbox', { name: guidedCopy('draft.label') })).not.toBeInTheDocument();
      expect(
        within(review).getByRole('heading', {
          level: 5,
          name: guidedCopy('draft.current_alt_label.public'),
        }),
      ).toBeInTheDocument();
    }
  });

  it('makes no network calls across choose → edit → apply → undo', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    choose('left', 'include');
    choose('right', 'include');
    const edited = 'Public-tab festival description.';
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByTestId('demo-apply-tribeca'));
    expect(screen.queryByTestId('demo-outcome')).not.toBeInTheDocument();
    await user.click(screen.getByTestId('demo-undo-tribeca'));

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(xhrOpen).not.toHaveBeenCalled();
    expect(xhrSend).not.toHaveBeenCalled();
  });

  it('keeps apply/undo in-tab and does not mutate the bundled example', async () => {
    const user = userEvent.setup();
    const seedBefore = structuredClone(createGuidedScenario());
    render(<RecordedWalkthrough scope="public" />);

    choose('left', 'include');
    choose('right', 'omit');
    const edited = 'Only this tab should keep this draft.';
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(screen.getByTestId('demo-apply-tribeca'));

    expect(sampleImage('tribeca')).toHaveAttribute('alt', edited);
    expect(editor).toHaveValue(edited);

    await user.click(screen.getByTestId('demo-undo-tribeca'));
    expect(sampleImage('tribeca')).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(editor).toHaveValue(edited);

    const seedAfter = createGuidedScenario();
    expect(seedAfter).toEqual(seedBefore);
    expect(seedAfter.pressPhoto.altText).toBe(SEED_ALT_TEXT);
  });

  it('keeps each public image status and manual edit independent through apply and undo', async () => {
    const user = userEvent.setup();
    const scenario = createGuidedScenario();
    render(<RecordedWalkthrough scope="public" />);

    chooseBothImages('left', 'include');
    chooseBothImages('right', 'include');

    const tribecaReview = screen.getByTestId('guided-description-review-tribeca');
    const coachellaReview = screen.getByTestId('guided-description-review-coachella');
    const tribecaEditor = publicEditor('tribeca');
    const coachellaEditor = publicEditor('coachella');
    const tribecaStatus = screen.getByTestId('guided-image-status-tribeca');
    const coachellaStatus = screen.getByTestId('guided-image-status-coachella');
    const originalTribecaAlt = scenario.pressPhotos[0].altText;
    const originalCoachellaAlt = scenario.pressPhotos[1].altText;
    const tribecaEdit = 'Tribeca manual edit stays local to this image.';
    const coachellaEdit = 'Coachella manual edit stays local to this image.';

    expect(tribecaStatus.textContent).toBe('');
    expect(coachellaStatus.textContent).toBe('');
    await user.clear(coachellaEditor);
    await user.type(coachellaEditor, coachellaEdit);
    await user.clear(tribecaEditor);
    await user.type(tribecaEditor, tribecaEdit);

    await user.click(screen.getByTestId('demo-apply-tribeca'));
    expect(sampleImage('tribeca')).toHaveAttribute('alt', tribecaEdit);
    expect(within(tribecaReview).getByTestId('guided-current-alt-tribeca')).toHaveTextContent(tribecaEdit);
    expect(tribecaStatus).toBe(screen.getByTestId('guided-image-status-tribeca'));
    expect(tribecaStatus).toHaveTextContent(guidedCopy('outcome.applied_image.public'));
    expect(sampleImage('coachella')).toHaveAttribute('alt', originalCoachellaAlt);
    expect(within(coachellaReview).getByTestId('guided-current-alt-coachella')).toHaveTextContent(originalCoachellaAlt);
    expect(coachellaEditor).toHaveValue(coachellaEdit);
    expect(coachellaStatus.textContent).toBe('');

    await user.click(screen.getByTestId('demo-undo-tribeca'));
    expect(sampleImage('tribeca')).toHaveAttribute('alt', originalTribecaAlt);
    expect(within(tribecaReview).getByTestId('guided-current-alt-tribeca')).toHaveTextContent(originalTribecaAlt);
    expect(tribecaEditor).toHaveValue(tribecaEdit);
    expect(tribecaStatus).toBe(screen.getByTestId('guided-image-status-tribeca'));
    expect(tribecaStatus).toHaveTextContent(guidedCopy('outcome.undone_image.public'));
    expect(coachellaStatus.textContent).toBe('');

    await user.click(screen.getByTestId('demo-apply-coachella'));
    expect(sampleImage('coachella')).toHaveAttribute('alt', coachellaEdit);
    expect(coachellaStatus).toHaveTextContent(guidedCopy('outcome.applied_image.public'));
    expect(sampleImage('tribeca')).toHaveAttribute('alt', originalTribecaAlt);
    expect(tribecaStatus).toHaveTextContent(guidedCopy('outcome.undone_image.public'));

    await user.click(screen.getByTestId('demo-undo-coachella'));
    expect(sampleImage('coachella')).toHaveAttribute('alt', originalCoachellaAlt);
    expect(coachellaEditor).toHaveValue(coachellaEdit);
    expect(coachellaStatus).toBe(screen.getByTestId('guided-image-status-coachella'));
    expect(coachellaStatus).toHaveTextContent(guidedCopy('outcome.undone_image.public'));
    expect(tribecaEditor).toHaveValue(tribecaEdit);
  });

  it('shows the complete current name-choice summary separately from live feedback', () => {
    render(<RecordedWalkthrough scope="public" />);

    const summary = screen.getByTestId('guided-choice-summary');
    expect(summary).toHaveTextContent('Justin Trudeau');
    expect(summary).toHaveTextContent('Katy Perry');
    expect(summary).toHaveTextContent(publicGuidedCopy('names.pending'));
    expect(screen.getByTestId('guided-page-feedback-status')).toHaveAttribute('aria-live', 'polite');

    choose('left', 'include');
    expect(summary).toHaveTextContent(publicGuidedCopy('names.use.public', { name: 'Justin Trudeau' }));
    expect(summary).toHaveTextContent(publicGuidedCopy('names.pending'));

    choose('right', 'omit');
    expect(summary).toHaveTextContent(publicGuidedCopy('names.use.public', { name: 'Justin Trudeau' }));
    expect(summary).toHaveTextContent(publicGuidedCopy('names.omit.public'));
  });

  it('keeps the full before-source attribution inside the provenance disclosure', () => {
    const { container } = render(<RecordedWalkthrough scope="public" />);
    const provenance = container.querySelector('.acx-guided-page__provenance-footer');
    expect(provenance).not.toBeNull();
    expect(provenance).toHaveTextContent(guidedCopy('context.source.summary.public'));
    expect(provenance).toHaveTextContent(guidedCopy('context.source.comparison_boundary.public'));
    expect(provenance).toHaveTextContent(guidedCopy('provenance.recorded'));
    expect(provenance?.querySelector('a[href="https://alttext.ai/"]')).toBeInTheDocument();
    const context = container.querySelector('.acx-guided-page__context');
    expect(context?.children).toHaveLength(1);
    expect(context?.querySelector('p')).toHaveTextContent(guidedCopy('context.purpose'));
    expect(context?.querySelector('details, button')).toBeNull();
  });

  it('keeps public-source narration out of admin provenance while retaining recorded attribution', () => {
    const { container } = render(<GuidedPrototypePage />);
    const provenance = container.querySelector('.acx-guided-page__provenance-footer');
    expect(provenance).not.toBeNull();
    expect(provenance).toHaveTextContent(guidedCopy('provenance.recorded'));
    expect(provenance).not.toHaveTextContent(guidedCopy('context.source.summary.public'));
    expect(provenance).not.toHaveTextContent(guidedCopy('context.source.comparison_boundary.public'));
    expect(provenance?.querySelector('a[href="https://alttext.ai/"]')).not.toBeInTheDocument();
    expect(container.querySelector('p.acx-guided-page__credit')).toHaveTextContent(
      createGuidedScenario().pressPhoto.credit,
    );
  });

  it('keeps public completion copy bounded for applied and kept outcomes', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    chooseBothImages('left', 'include');
    chooseBothImages('right', 'include');
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    await user.clear(editor);
    await user.type(editor, 'A bounded public demo edit.');
    await user.click(screen.getByTestId('demo-apply-tribeca'));
    expect(screen.queryByTestId('demo-outcome')).not.toBeInTheDocument();

    await user.click(
      within(screen.getByTestId('guided-description-review-coachella')).getByRole('button', {
        name: publicGuidedCopy('description.keep.public'),
      }),
    );
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.scope.public'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.next_batch.public'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(
      publicGuidedCopy('outcome.applied.public', { photoName: 'Tribeca Festival, New York, June 2026' }),
    );
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(
      publicGuidedCopy('outcome.kept.public', { photoName: 'Coachella festival photo, 2026' }),
    );
    expect(screen.getByTestId('demo-outcome')).not.toHaveTextContent(/WordPress media has been updated/i);
  });

  it('keeps reset local and clears choices, draft state, and outcome', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    chooseBothImages('left', 'include');
    chooseBothImages('right', 'omit');
    await user.click(screen.getByRole('button', { name: publicGuidedCopy('reset.confirm.public') }));
    const dialog = screen.getByRole('dialog', { name: publicGuidedCopy('reset.title.public') });
    await user.click(within(dialog).getByRole('button', { name: publicGuidedCopy('reset.confirm.public') }));

    expect(
      within(screen.getByTestId('name-choice-tribeca-left')).getByRole('radio', { name: /^Use / }),
    ).not.toBeChecked();
    expect(
      within(screen.getByTestId('name-choice-tribeca-right')).getByRole('radio', { name: /^Use / }),
    ).not.toBeChecked();
    expect(screen.getByTestId('guided-choice-summary')).toHaveTextContent(publicGuidedCopy('names.pending'));
    expect(screen.queryByTestId('demo-outcome')).not.toBeInTheDocument();
    expect(screen.getByTestId('guided-description-review-tribeca')).toHaveTextContent(
      publicGuidedCopy('choices.help.public'),
    );
  });

  it('returns focus to the first name question after Start over is confirmed', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    const firstNameQuestion = within(screen.getByTestId('name-choice-tribeca-left')).getByRole('radio', {
      name: publicGuidedCopy('names.use.public', { name: 'Justin Trudeau' }),
    });
    const focusFirstNameQuestion = vi.spyOn(firstNameQuestion, 'focus');
    await user.click(screen.getByRole('button', { name: publicGuidedCopy('reset.confirm.public') }));
    const dialog = screen.getByRole('dialog', { name: publicGuidedCopy('reset.title.public') });
    await user.click(within(dialog).getByRole('button', { name: publicGuidedCopy('reset.confirm.public') }));

    expect(document.activeElement).toBe(firstNameQuestion);
    expect(focusFirstNameQuestion).toHaveBeenCalledWith({ preventScroll: true });
  });

  it('returns focus to the changed name radio after confirming a name change', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);
    choose('left', 'include');
    choose('right', 'include');
    const editor = publicEditor('tribeca');
    await user.clear(editor);
    await user.type(editor, 'A visitor edit that needs a focus return.');

    const changedNameRadio = within(screen.getByTestId('name-choice-tribeca-right')).getByRole('radio', {
      name: publicGuidedCopy('names.omit.public'),
    });
    const focusChangedNameRadio = vi.spyOn(changedNameRadio, 'focus');
    fireEvent.click(changedNameRadio);
    const dialog = screen.getByRole('dialog', { name: publicGuidedCopy('name_change.title.public') });
    await user.click(within(dialog).getByRole('button', { name: publicGuidedCopy('name_change.confirm.public') }));

    expect(changedNameRadio).toBeChecked();
    expect(document.activeElement).toBe(changedNameRadio);
    expect(focusChangedNameRadio).toHaveBeenCalledWith({ preventScroll: true });
  });

  it('returns focus to the clicked radio when a visitor keeps their edits', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);
    choose('left', 'include');
    choose('right', 'include');
    const editor = publicEditor('tribeca');
    await user.clear(editor);
    await user.type(editor, 'A visitor edit kept after changing their mind.');

    const clickedRadio = within(screen.getByTestId('name-choice-tribeca-right')).getByRole('radio', {
      name: publicGuidedCopy('names.omit.public'),
    });
    fireEvent.click(clickedRadio);
    const dialog = screen.getByRole('dialog', { name: publicGuidedCopy('name_change.title.public') });
    await user.click(within(dialog).getByRole('button', { name: publicGuidedCopy('name_change.keep.public') }));

    expect(document.activeElement).toBe(clickedRadio);
    expect(clickedRadio).not.toBeChecked();
    expect(editor).toHaveValue('A visitor edit kept after changing their mind.');
  });

  it('does not resurrect an unsaved draft or open replacement after reset', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    const scenario = createGuidedScenario();
    choose('left', 'include');
    choose('right', 'include');
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    const staleDraft = 'Unsaved draft must not return after reset.';
    fireEvent.change(editor, { target: { value: staleDraft } });

    await user.click(screen.getByRole('button', { name: publicGuidedCopy('reset.confirm.public') }));
    const dialog = screen.getByRole('dialog', { name: publicGuidedCopy('reset.title.public') });
    await user.click(within(dialog).getByRole('button', { name: publicGuidedCopy('reset.confirm.public') }));

    choose('left', 'include');
    choose('right', 'omit');

    expect(
      screen.queryByRole('dialog', { name: publicGuidedCopy('name_change.title.public') }),
    ).not.toBeInTheDocument();
    const resetEditor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    expect(resetEditor).toHaveValue(scenario.samples.tribeca['justin-trudeau']);
    expect(resetEditor).not.toHaveValue(staleDraft);
  });

  it('resets both public image drafts, applied previews, statuses, and choices', async () => {
    const user = userEvent.setup();
    const scenario = createGuidedScenario();
    render(<RecordedWalkthrough scope="public" />);

    chooseBothImages('left', 'include');
    chooseBothImages('right', 'include');
    const tribecaEditor = publicEditor('tribeca');
    const coachellaEditor = publicEditor('coachella');
    const tribecaEdit = 'Stale Tribeca edit must be cleared by reset.';
    const coachellaEdit = 'Stale Coachella edit must be cleared by reset.';
    await user.clear(tribecaEditor);
    await user.type(tribecaEditor, tribecaEdit);
    await user.clear(coachellaEditor);
    await user.type(coachellaEditor, coachellaEdit);
    await user.click(screen.getByTestId('demo-apply-tribeca'));
    await user.click(screen.getByTestId('demo-apply-coachella'));

    await user.click(screen.getByRole('button', { name: publicGuidedCopy('reset.confirm.public') }));
    const dialog = screen.getByRole('dialog', { name: publicGuidedCopy('reset.title.public') });
    await user.click(within(dialog).getByRole('button', { name: publicGuidedCopy('reset.confirm.public') }));

    for (const imageKey of PUBLIC_IMAGE_KEYS) {
      const photo = screen.getByTestId(`guided-photo-${imageKey}`);
      const fieldsetLeft = within(photo).getByTestId(`name-choice-${imageKey}-left`);
      const fieldsetRight = within(photo).getByTestId(`name-choice-${imageKey}-right`);
      expect(
        within(fieldsetLeft)
          .getAllByRole('radio')
          .every((radio) => !(radio as HTMLInputElement).checked),
      ).toBe(true);
      expect(
        within(fieldsetRight)
          .getAllByRole('radio')
          .every((radio) => !(radio as HTMLInputElement).checked),
      ).toBe(true);
      const review = screen.getByTestId(`guided-description-review-${imageKey}`);
      expect(review).toHaveTextContent(publicGuidedCopy('choices.help.public'));
      expect(
        within(review).queryByRole('textbox', { name: guidedCopy('draft.field_label.public') }),
      ).not.toBeInTheDocument();
      expect(sampleImage(imageKey)).toHaveAttribute(
        'alt',
        scenario.pressPhotos.find((photo) => photo.key === imageKey)?.altText,
      );
      expect(screen.queryByTestId(`guided-image-status-${imageKey}`)).not.toBeInTheDocument();
    }
    expect(screen.getByTestId('guided-choice-summary')).toHaveTextContent(publicGuidedCopy('names.pending'));
    expect(screen.queryByTestId('demo-outcome')).not.toBeInTheDocument();

    chooseBothImages('left', 'include');
    chooseBothImages('right', 'include');
    expect(publicEditor('tribeca')).toHaveValue(scenario.samples.tribeca.both);
    expect(publicEditor('tribeca')).not.toHaveValue(tribecaEdit);
    expect(publicEditor('coachella')).toHaveValue(scenario.samples.coachella.both);
    expect(publicEditor('coachella')).not.toHaveValue(coachellaEdit);
    expect(sampleImage('tribeca')).toHaveAttribute('alt', scenario.pressPhotos[0].altText);
    expect(sampleImage('coachella')).toHaveAttribute('alt', scenario.pressPhotos[1].altText);
  });

  it('walks the public entry import graph and forbids live/API imports', () => {
    const pluginRoot = resolve(__dirname, '../../..');
    const files = collectImportGraph(resolve(pluginRoot, 'js/guide/main.tsx'));

    expect(files.length).toBeLessThanOrEqual(MAX_PUBLIC_GRAPH_FILES);
    expect(files.some((file) => file.endsWith('GuidedFacesPanel.tsx'))).toBe(false);
    expect(files.some((file) => file.endsWith('GuidedDescriptionReview.tsx'))).toBe(true);
    expect(files.some((file) => file.endsWith('GuidedFaceMatchCard.tsx'))).toBe(true);
    expect(files.some((file) => file.endsWith('state.ts'))).toBe(true);
    expect(files.some((file) => file.includes('GuidedLiveDescriptionPanel'))).toBe(false);
    expect(files.some((file) => file.includes('useGuidedLiveDescription'))).toBe(false);
    expect(forbiddenImportHits(files), forbiddenImportHits(files).join('; ')).toEqual([]);
  });

  it('fails closed when a nested reachable module imports a live/API surface (canary)', () => {
    const root = mkdtempSync(join(tmpdir(), 'acx-public-boundary-'));
    try {
      const child = join(root, 'child.tsx');
      const entry = join(root, 'entry.tsx');
      writeFileSync(
        child,
        "import { GuidedLiveDescriptionPanel } from 'GuidedLiveDescriptionPanel';\nexport const leak = GuidedLiveDescriptionPanel;\n",
      );
      writeFileSync(entry, "import { leak } from './child';\nexport const root = leak;\n");
      const files = collectImportGraph(entry);
      expect(files.some((file) => file.endsWith('child.tsx'))).toBe(true);
      const hits = forbiddenImportHits(files);
      expect(hits.length, 'canary must fail when a descendant imports a live/API surface').toBeGreaterThan(0);
      expect(() => collectImportGraph(entry, 1)).toThrow(/exceeded 1/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
