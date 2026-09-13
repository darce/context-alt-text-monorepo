import { existsSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';

import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CASE_STUDY_URL, guidedCopy } from '../../admin/guidedPrototype/publicGuideCopy';
import { RecordedWalkthrough } from '../../admin/guidedPrototype/RecordedWalkthrough';
import { createGuidedScenario } from '../../admin/guidedPrototype/state';

const SEED_ALT_TEXT =
  'A man in a black suit and a woman in a white dress pose together, smiling, in front of a Tribeca Festival step-and-repeat backdrop.';
const PUBLIC_HOME_URL = 'https://altcontext.com/';

const PUBLIC_IMAGE_KEYS = ['tribeca', 'coachella'] as const;
type PublicImageKey = (typeof PUBLIC_IMAGE_KEYS)[number];

const choose = (
  position: 'left' | 'right',
  option: 'include' | 'omit',
  imageKey: PublicImageKey = 'tribeca',
): void => {
  const photo = screen.getByTestId(`guided-photo-${imageKey}`);
  const fieldset = within(photo).getByTestId(`name-choice-${imageKey}-${position}`);
  const name =
    option === 'include'
      ? guidedCopy('names.include', { name: position === 'left' ? 'Justin Trudeau' : 'Katy Perry' })
      : guidedCopy('names.omit');
  fireEvent.click(within(fieldset).getByRole('radio', { name }));
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
    expect(screen.getByRole('button', { name: guidedCopy('page.start') })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: `${guidedCopy('entry.read_case_study')} (opens in a new window)` }),
    ).toHaveAttribute('href', CASE_STUDY_URL);

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

  it('keeps the public flow to two stages and guards image actions in the zero state', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    const stepper = screen.getByTestId('guided-demo-stepper');
    const chooseNames = within(stepper).getByRole('button', { name: guidedCopy('step.names.public') });
    const reviewAndApply = within(stepper).getByRole('button', { name: guidedCopy('step.review.public') });
    expect(within(stepper).getAllByRole('button')).toHaveLength(3);
    expect(stepper).toHaveTextContent(
      guidedCopy('guide.current.public', {
        stepNumber: 1,
        stepCount: 2,
        stepTitle: guidedCopy('step.names.public'),
      }),
    );
    expect(chooseNames).toHaveAttribute('aria-controls', 'guided-section-understand');
    expect(reviewAndApply).toHaveAttribute('aria-controls', 'guided-section-review');
    expect(chooseNames).toHaveAttribute('aria-current', 'step');
    expect(stepper.querySelectorAll('[aria-current="step"]')).toHaveLength(1);
    const reviewDrafts = screen.getByTestId('guided-review-draft');
    expect(reviewDrafts).toBeDisabled();

    for (const imageKey of PUBLIC_IMAGE_KEYS) {
      expect(screen.getByTestId(`demo-apply-${imageKey}`)).toBeDisabled();
      expect(screen.getByTestId(`demo-undo-${imageKey}`)).toBeDisabled();
      expect(screen.getByTestId(`guided-image-status-${imageKey}`)).toHaveAttribute('role', 'status');
    }
    expect(screen.getByTestId('guided-choices-help')).toHaveTextContent(guidedCopy('choices.help.public'));

    choose('left', 'include');
    expect(reviewDrafts).toBeDisabled();
    expect(screen.getByTestId('demo-apply-tribeca')).toBeDisabled();
    choose('right', 'omit');
    expect(reviewDrafts).toBeEnabled();
    expect(screen.getByTestId('demo-apply-tribeca')).toBeEnabled();
    expect(screen.getByTestId('demo-apply-coachella')).toBeEnabled();

    await user.click(reviewDrafts);
    expect(document.activeElement).toHaveAttribute('id', 'guided-section-review');
    expect(stepper).toHaveTextContent(
      guidedCopy('guide.current.public', {
        stepNumber: 2,
        stepCount: 2,
        stepTitle: guidedCopy('step.review.public'),
      }),
    );
    expect(reviewAndApply).toHaveAttribute('aria-current', 'step');
    expect(chooseNames).not.toHaveAttribute('aria-current', 'step');
    expect(stepper.querySelectorAll('[aria-current="step"]')).toHaveLength(1);
  });

  it('keeps public headings and editor labels scoped to both source images', () => {
    render(<RecordedWalkthrough scope="public" />);

    expect(screen.getByText(guidedCopy('entry.eyebrow.public'))).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: guidedCopy('entry.title.public') })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: guidedCopy('step.names.public') })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: guidedCopy('step.review.public') })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 4, name: guidedCopy('faces.title.public') })).toHaveLength(2);
    expect(
      screen.getAllByRole('heading', { level: 4, name: guidedCopy('comparison.altcontext.public') }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole('heading', { level: 4, name: guidedCopy('comparison.alttextai.public') }),
    ).toHaveLength(2);
    expect(
      screen.queryByRole('heading', { name: guidedCopy('context.photo.altcontext_title') }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: guidedCopy('context.photo.alttextai_title') }),
    ).not.toBeInTheDocument();

    choose('left', 'include');
    choose('right', 'include');
    for (const imageKey of PUBLIC_IMAGE_KEYS) {
      const review = screen.getByTestId(`guided-description-review-${imageKey}`);
      expect(
        within(review).getByRole('textbox', { name: guidedCopy('draft.field_label.public') }),
      ).toBeInTheDocument();
      expect(within(review).queryByRole('textbox', { name: guidedCopy('draft.label') })).not.toBeInTheDocument();
      expect(
        within(review).getByRole('heading', {
          level: 4,
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

    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', edited);
    expect(editor).toHaveValue(edited);

    await user.click(screen.getByTestId('demo-undo-tribeca'));
    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', SEED_ALT_TEXT);
    expect(editor).toHaveValue(edited);

    const seedAfter = createGuidedScenario();
    expect(seedAfter).toEqual(seedBefore);
    expect(seedAfter.pressPhoto.altText).toBe(SEED_ALT_TEXT);
  });

  it('keeps each public image status and manual edit independent through apply and undo', async () => {
    const user = userEvent.setup();
    const scenario = createGuidedScenario();
    render(<RecordedWalkthrough scope="public" />);

    choose('left', 'include');
    choose('right', 'include');

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
    expect(within(tribecaReview).getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', tribecaEdit);
    expect(within(tribecaReview).getByTestId('guided-current-alt-tribeca')).toHaveTextContent(tribecaEdit);
    expect(tribecaStatus).toBe(screen.getByTestId('guided-image-status-tribeca'));
    expect(tribecaStatus).toHaveTextContent(guidedCopy('outcome.applied_image.public'));
    expect(within(coachellaReview).getByTestId('demo-applied-image-coachella')).toHaveAttribute(
      'alt',
      originalCoachellaAlt,
    );
    expect(within(coachellaReview).getByTestId('guided-current-alt-coachella')).toHaveTextContent(originalCoachellaAlt);
    expect(coachellaEditor).toHaveValue(coachellaEdit);
    expect(coachellaStatus.textContent).toBe('');

    await user.click(screen.getByTestId('demo-undo-tribeca'));
    expect(within(tribecaReview).getByTestId('demo-applied-image-tribeca')).toHaveAttribute(
      'alt',
      originalTribecaAlt,
    );
    expect(within(tribecaReview).getByTestId('guided-current-alt-tribeca')).toHaveTextContent(originalTribecaAlt);
    expect(tribecaEditor).toHaveValue(tribecaEdit);
    expect(tribecaStatus).toBe(screen.getByTestId('guided-image-status-tribeca'));
    expect(tribecaStatus).toHaveTextContent(guidedCopy('outcome.undone_image.public'));
    expect(coachellaStatus.textContent).toBe('');

    await user.click(screen.getByTestId('demo-apply-coachella'));
    expect(within(coachellaReview).getByTestId('demo-applied-image-coachella')).toHaveAttribute('alt', coachellaEdit);
    expect(coachellaStatus).toHaveTextContent(guidedCopy('outcome.applied_image.public'));
    expect(within(tribecaReview).getByTestId('demo-applied-image-tribeca')).toHaveAttribute(
      'alt',
      originalTribecaAlt,
    );
    expect(tribecaStatus).toHaveTextContent(guidedCopy('outcome.undone_image.public'));

    await user.click(screen.getByTestId('demo-undo-coachella'));
    expect(within(coachellaReview).getByTestId('demo-applied-image-coachella')).toHaveAttribute(
      'alt',
      originalCoachellaAlt,
    );
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
    expect(summary).toHaveTextContent(guidedCopy('names.pending'));
    expect(screen.getByTestId('guided-page-feedback-status')).toHaveAttribute('aria-live', 'polite');

    choose('left', 'include');
    expect(summary).toHaveTextContent(guidedCopy('names.include', { name: 'Justin Trudeau' }));
    expect(summary).toHaveTextContent(guidedCopy('names.pending'));

    choose('right', 'omit');
    expect(summary).toHaveTextContent(guidedCopy('names.include', { name: 'Justin Trudeau' }));
    expect(summary).toHaveTextContent(guidedCopy('names.omit'));
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
    const { container } = render(<RecordedWalkthrough scope="admin" />);
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

    choose('left', 'include');
    choose('right', 'include');
    const editor = within(screen.getByTestId('guided-draft-field-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.field_label.public'),
    });
    await user.clear(editor);
    await user.type(editor, 'A bounded public demo edit.');
    await user.click(screen.getByTestId('demo-apply-tribeca'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.scope.public'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.next_batch.public'));
    expect(screen.getByTestId('demo-outcome')).not.toHaveTextContent(/WordPress media has been updated/i);

    await user.click(screen.getByRole('button', { name: guidedCopy('outcome.return') }));
    await user.click(
      within(screen.getByTestId('guided-description-review-tribeca')).getByRole('button', {
        name: guidedCopy('draft.keep'),
      }),
    );
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.kept'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.scope.public'));
    expect(screen.getByTestId('demo-outcome')).toHaveTextContent(guidedCopy('outcome.next_batch.public'));
  });

  it('keeps reset local and clears choices, draft state, and outcome', async () => {
    const user = userEvent.setup();
    render(<RecordedWalkthrough scope="public" />);

    choose('left', 'include');
    choose('right', 'omit');
    await user.click(screen.getByRole('button', { name: guidedCopy('page.reset') }));
    const dialog = screen.getByRole('dialog', { name: guidedCopy('reset.title') });
    await user.click(within(dialog).getByRole('button', { name: guidedCopy('reset.confirm') }));

    expect(
      within(screen.getByTestId('name-choice-tribeca-left')).getByRole('radio', { name: /^Use / }),
    ).not.toBeChecked();
    expect(
      within(screen.getByTestId('name-choice-tribeca-right')).getByRole('radio', { name: /^Use / }),
    ).not.toBeChecked();
    expect(screen.getByTestId('guided-choice-summary')).toHaveTextContent(guidedCopy('names.pending'));
    expect(screen.queryByTestId('demo-outcome')).not.toBeInTheDocument();
    expect(screen.getByTestId('guided-description-review-tribeca')).toHaveTextContent(guidedCopy('draft.blocked'));
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

    await user.click(screen.getByRole('button', { name: guidedCopy('page.reset') }));
    const dialog = screen.getByRole('dialog', { name: guidedCopy('reset.title') });
    await user.click(within(dialog).getByRole('button', { name: guidedCopy('reset.confirm') }));

    choose('left', 'include');
    choose('right', 'omit');

    expect(screen.queryByRole('dialog', { name: guidedCopy('names.change_title') })).not.toBeInTheDocument();
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

    choose('left', 'include');
    choose('right', 'include');
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

    await user.click(screen.getByRole('button', { name: guidedCopy('page.reset') }));
    const dialog = screen.getByRole('dialog', { name: guidedCopy('reset.title') });
    await user.click(within(dialog).getByRole('button', { name: guidedCopy('reset.confirm') }));

    for (const imageKey of PUBLIC_IMAGE_KEYS) {
      const photo = screen.getByTestId(`guided-photo-${imageKey}`);
      const fieldsetLeft = within(photo).getByTestId(`name-choice-${imageKey}-left`);
      const fieldsetRight = within(photo).getByTestId(`name-choice-${imageKey}-right`);
      expect(
        within(fieldsetLeft).getAllByRole('radio').every((radio) => !(radio as HTMLInputElement).checked),
      ).toBe(true);
      expect(
        within(fieldsetRight).getAllByRole('radio').every((radio) => !(radio as HTMLInputElement).checked),
      ).toBe(true);
      const review = screen.getByTestId(`guided-description-review-${imageKey}`);
      expect(review).toHaveTextContent(guidedCopy('draft.blocked'));
      expect(
        within(review).queryByRole('textbox', { name: guidedCopy('draft.field_label.public') }),
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId(`demo-applied-image-${imageKey}`)).not.toBeInTheDocument();
      expect(screen.getByTestId(`guided-image-status-${imageKey}`).textContent).toBe('');
    }
    expect(screen.getByTestId('guided-choice-summary')).toHaveTextContent(guidedCopy('names.pending'));
    expect(screen.queryByTestId('demo-outcome')).not.toBeInTheDocument();

    choose('left', 'include');
    choose('right', 'include');
    expect(publicEditor('tribeca')).toHaveValue(scenario.samples.tribeca.both);
    expect(publicEditor('tribeca')).not.toHaveValue(tribecaEdit);
    expect(publicEditor('coachella')).toHaveValue(scenario.samples.coachella.both);
    expect(publicEditor('coachella')).not.toHaveValue(coachellaEdit);
    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', scenario.pressPhotos[0].altText);
    expect(screen.getByTestId('demo-applied-image-coachella')).toHaveAttribute('alt', scenario.pressPhotos[1].altText);
  });

  it('walks the public entry import graph and forbids live/API imports', () => {
    const pluginRoot = resolve(__dirname, '../../..');
    const files = collectImportGraph(resolve(pluginRoot, 'js/guide/main.tsx'));

    expect(files.length).toBeLessThanOrEqual(MAX_PUBLIC_GRAPH_FILES);
    expect(files.some((file) => file.endsWith('GuidedFacesPanel.tsx'))).toBe(true);
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
