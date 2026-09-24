import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/publicGuideCopy';
import { createGuidedScenario, formatGuidedSimilarity, getGuidedFace } from '../../../guidedPrototype/state';
import { GuidedSamplePhoto } from '../GuidedSamplePhoto';

describe('GuidedSamplePhoto image geometry', () => {
  it('sets the loaded image ratio on the wrap used by the percentage overlay', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhoto;

    render(
      <GuidedSamplePhoto
        photo={photo}
        currentAltText={photo.altText}
        showCurrentAltText={false}
        scope="admin"
        headingId="guided-photo-tribeca-title"
      />,
    );

    const image = screen.getByRole('img', { name: photo.altText });
    const wrap = image.closest('.acx-guided-page__image-wrap');
    expect(wrap).toBeInstanceOf(HTMLElement);
    expect(wrap).toHaveAttribute('data-orientation', 'landscape');
    expect((wrap as HTMLElement).style.aspectRatio).toBe('');
    expect((wrap as HTMLElement).style.getPropertyValue('--acx-guided-photo-ratio')).toBe('');

    const frame = wrap?.querySelector('.acx-guided-page__image-frame');
    expect(frame).toBeInstanceOf(HTMLElement);
    expect(frame).toContainElement(image);

    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 1000 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 800 });
    fireEvent.load(image);

    expect(wrap).toHaveAttribute('data-orientation', 'landscape');
    expect((wrap as HTMLElement).style.getPropertyValue('--acx-guided-photo-ratio')).toBe('1000 / 800');
    expect((wrap as HTMLElement).style.aspectRatio).toBe('');

    const justinFace = getGuidedFace(scenario, 'tribeca-justin-trudeau');
    const outline = screen.getByRole('button', { name: /Justin Trudeau, 89\.4%/ });
    expect(outline).toHaveStyle({
      left: `${(justinFace.box.x / 1000) * 100}%`,
      top: `${(justinFace.box.y / 800) * 100}%`,
    });

    const anchorFace = scenario.faces.find((face) => face.imageKey === photo.key && face.isClusterAnchor);
    expect(anchorFace).toBeDefined();
    const anchorButton = screen.getByTestId('guided-face-overlay').querySelector(`[data-face-id="${anchorFace?.id}"]`);
    expect(anchorButton?.getAttribute('aria-label')).toContain(formatGuidedSimilarity(anchorFace!.similarity!));
    expect(anchorButton?.getAttribute('aria-label')).not.toContain(guidedCopy('names.no_score.public'));
  });

  it('marks a loaded portrait image as portrait', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhotos[1];

    render(<GuidedSamplePhoto photo={photo} currentAltText={photo.altText} showCurrentAltText={false} scope="admin" />);

    const image = screen.getByRole('img', { name: photo.altText });
    const wrap = image.closest('.acx-guided-page__image-wrap');
    expect(wrap).toBeInstanceOf(HTMLElement);

    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 640 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 852 });
    fireEvent.load(image);

    expect(wrap).toHaveAttribute('data-orientation', 'portrait');
    expect((wrap as HTMLElement).style.getPropertyValue('--acx-guided-photo-ratio')).toBe('640 / 852');
  });
});

describe('GuidedSamplePhoto figure content', () => {
  it('keeps the admin overlay chip similarity as a bare percentage', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhotos[0];
    render(<GuidedSamplePhoto photo={photo} currentAltText={photo.altText} showCurrentAltText={false} scope="admin" />);

    const image = screen.getByRole('img', { name: photo.altText });
    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 1000 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 800 });
    fireEvent.load(image);

    const justinFace = getGuidedFace(scenario, 'tribeca-justin-trudeau');
    const overlay = screen.getByTestId('guided-face-overlay');
    const chip = overlay.querySelector(`[data-face-id="${justinFace.id}"] .acx-guided-face-overlay__chip-label`);

    expect(chip).toHaveTextContent('89.4%');
    expect(chip).not.toHaveTextContent('89.4% match');
  });

  it('shows both public descriptions and their provenance in an open comparison caption', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhotos[1];
    const currentDescription = 'The current description for this photo.';
    const { container } = render(
      <GuidedSamplePhoto
        photo={photo}
        evidenceAlt={photo.altContextDescription.text}
        currentAltText={currentDescription}
        showCurrentAltText
        scope="public"
        headingId="guided-photo-coachella-title"
      >
        <article data-testid="faces-slot">Faces</article>
      </GuidedSamplePhoto>,
    );

    const figure = screen.getByTestId('guided-photo-coachella');
    const heading = screen.getByRole('heading', { level: 3, name: photo.event });
    expect(heading).toHaveAttribute('id', 'guided-photo-coachella-title');
    expect(figure).toHaveAttribute('aria-labelledby', 'guided-photo-coachella-title');
    const image = screen.getByRole('img', { name: currentDescription });
    expect(image).toHaveAttribute('alt', currentDescription);
    expect(screen.queryByRole('img', { name: photo.altContextDescription.text })).not.toBeInTheDocument();

    const wrap = figure.querySelector('.acx-guided-page__image-wrap');
    const credit = figure.querySelector('p.acx-guided-page__credit');
    const figcaption = figure.querySelector('figcaption');
    const slot = screen.getByTestId('faces-slot');
    expect(wrap).toBeInstanceOf(HTMLElement);
    expect(credit).toBeInstanceOf(HTMLParagraphElement);
    expect(wrap?.nextElementSibling).toBe(credit);
    expect(credit?.nextElementSibling).toBe(figcaption);
    expect(credit).toHaveTextContent(`Photo credit: ${photo.credit}`);
    expect(credit?.closest('details')).toBeNull();
    expect(credit?.querySelector('a')).toHaveAttribute('href', photo.credit);

    const comparisonDetails = figure.querySelector('details.acx-guided-page__caption');
    expect(comparisonDetails).toBeInstanceOf(HTMLDetailsElement);
    expect(comparisonDetails).toHaveAttribute('open');
    const comparison = within(comparisonDetails as HTMLDetailsElement);
    expect(comparison.getByText(guidedCopy('comparison.title.public'))).toBeInTheDocument();
    expect(
      comparison.getByRole('heading', { level: 4, name: guidedCopy('comparison.altcontext.public') }),
    ).toBeInTheDocument();
    expect(
      comparison.getByRole('heading', { level: 4, name: guidedCopy('comparison.alttextai.public') }),
    ).toBeInTheDocument();
    expect(comparison.getByText(photo.altContextDescription.text)).toBeInTheDocument();
    if (photo.altTextAiCaption.text === null) {
      expect(comparison.getByText(guidedCopy('context.photo.no_caption'))).toBeInTheDocument();
    } else {
      expect(comparison.getByText(photo.altTextAiCaption.text)).toBeInTheDocument();
    }
    const altContextLink = comparison.getByRole('link', {
      name: guidedCopy('context.external_link', { label: photo.altContextDescription.system }),
    });
    expect(altContextLink).toHaveAttribute('href', photo.altContextDescription.systemUrl);
    expect(altContextLink.closest('p')).toHaveClass('acx-guided-page__caption-provenance');
    expect(altContextLink.closest('p')).toHaveTextContent(photo.altContextDescription.generatedOn);

    const captionProvenance = comparison.getByText(/Captured 10 September 2026\./, {
      selector: 'p.acx-guided-page__caption-provenance',
    });
    expect(captionProvenance.textContent).toBe('AltText.ai · Captured 10 September 2026.');
    expect(comparison.getByText(guidedCopy('comparison.note.public'))).toBeInTheDocument();
    expect(comparisonDetails).not.toHaveTextContent(photo.altTextAiCaption.note);

    expect(figcaption).not.toContainElement(slot);
    expect(figure.lastElementChild).toBe(slot);
    expect(container.querySelectorAll('section.acx-guided-page__caption')).toHaveLength(2);
    expect(figcaption).not.toHaveTextContent('Current alt text in the demo copy:');
  });

  it('keeps the current description and comparison captions for the admin scope', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhotos[0];
    const currentDescription = 'The current admin description for this photo.';
    const { container } = render(
      <GuidedSamplePhoto photo={photo} currentAltText={currentDescription} showCurrentAltText scope="admin" />,
    );

    const figure = container.querySelector('figure');
    expect(figure).toBeInstanceOf(HTMLElement);
    expect(
      within(figure as HTMLElement).getByText(`${guidedCopy('context.current_label')}: ${currentDescription}`),
    ).toBeInTheDocument();
    expect(
      within(figure as HTMLElement).getByRole('heading', {
        level: 4,
        name: guidedCopy('context.photo.altcontext_title'),
      }),
    ).toBeInTheDocument();
    expect(within(figure as HTMLElement).getByText(photo.altContextDescription.text)).toBeInTheDocument();
    expect(
      within(figure as HTMLElement).getByRole('heading', {
        level: 4,
        name: guidedCopy('context.photo.alttextai_title'),
      }),
    ).toBeInTheDocument();
    if (photo.altTextAiCaption.text === null) {
      expect(within(figure as HTMLElement).getByText(guidedCopy('context.photo.no_caption'))).toBeInTheDocument();
    } else {
      expect(within(figure as HTMLElement).getByText(photo.altTextAiCaption.text)).toBeInTheDocument();
    }
    expect(figure?.querySelector('details.acx-guided-page__caption')).toBeNull();
  });

  it('shows formatted similarity values for scored public matches and no score for the anchor', () => {
    const scenario = createGuidedScenario();
    const photo = scenario.pressPhotos[0];
    render(
      <GuidedSamplePhoto photo={photo} currentAltText={photo.altText} showCurrentAltText={false} scope="public" />,
    );

    const image = screen.getByRole('img', { name: photo.altText });
    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 1000 });
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 800 });
    fireEvent.load(image);

    const overlay = screen.getByTestId('guided-face-overlay');
    const buttons = within(overlay).getAllByRole('button');
    const photoFaces = scenario.faces.filter((face) => face.imageKey === photo.key);
    expect(buttons).toHaveLength(photoFaces.length);

    for (const button of buttons) {
      const face = photoFaces.find((candidate) => candidate.id === button.getAttribute('data-face-id'));
      expect(face).toBeDefined();
      const chipText = button.querySelector('.acx-guided-face-overlay__chip-label')?.textContent ?? '';
      const accessibleName = button.getAttribute('aria-label') ?? '';
      const publicText = `${chipText} ${accessibleName}`;
      if (face?.isClusterAnchor) {
        expect(publicText).toContain(guidedCopy('names.no_score.public'));
        expect(publicText).not.toMatch(/100%/);
      } else if (face?.similarity !== null && face?.similarity !== undefined) {
        expect(publicText).toContain(formatGuidedSimilarity(face.similarity));
      }
    }

    const anchor = photoFaces.find((face) => face.isClusterAnchor);
    if (anchor !== undefined) {
      const anchorButton = overlay.querySelector(`[data-face-id="${anchor.id}"]`);
      expect(anchorButton?.getAttribute('aria-label')).toContain(guidedCopy('names.no_score.public'));
      expect(anchorButton?.getAttribute('aria-label')).not.toMatch(/100%/);
      expect(anchorButton?.textContent).not.toMatch(/100%/);
    }
  });
});
