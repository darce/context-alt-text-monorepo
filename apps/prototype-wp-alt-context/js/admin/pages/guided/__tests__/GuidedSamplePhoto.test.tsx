import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/publicGuideCopy';
import { createGuidedScenario, getGuidedFace } from '../../../guidedPrototype/state';
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
    const outline = screen.getByRole('button', { name: /Justin Trudeau, Strong match/ });
    expect(outline).toHaveStyle({
      left: `${(justinFace.box.x / 1000) * 100}%`,
      top: `${(justinFace.box.y / 800) * 100}%`,
    });
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
  it('uses the current description as image alt and collapses the comparison caption', () => {
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

    const altTextAiDetails = figure.querySelector('details.acx-guided-page__caption');
    expect(altTextAiDetails).toBeInstanceOf(HTMLDetailsElement);
    expect(altTextAiDetails).not.toHaveAttribute('open');
    expect(altTextAiDetails).toContainElement(
      within(altTextAiDetails as HTMLDetailsElement).getByText('How another tool describes this photo'),
    );
    expect(altTextAiDetails).toHaveTextContent('For comparison only, not a benchmark.');
    expect(altTextAiDetails).not.toHaveTextContent(photo.altContextDescription.text);
    const captionProvenance = within(altTextAiDetails as HTMLDetailsElement).getByText(/Captured 10 September 2026\./, {
      selector: 'p.acx-guided-page__caption-provenance',
    });
    expect(captionProvenance.textContent).toBe('AltText.ai · Captured 10 September 2026.');
    expect(captionProvenance).not.toHaveTextContent(photo.altTextAiCaption.note);

    expect(figcaption).not.toContainElement(slot);
    expect(figure.lastElementChild).toBe(slot);
    expect(container.querySelectorAll('section.acx-guided-page__caption')).toHaveLength(0);
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

  it('does not expose similarity values in the public overlay chip or accessible names', () => {
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
      expect(publicText).not.toMatch(/\d+\s*%/);
      if (face?.similarity !== null && face?.similarity !== undefined) {
        expect(publicText).not.toContain(String(face.similarity));
      }
    }

    const anchor = photoFaces.find((face) => face.isClusterAnchor);
    if (anchor !== undefined) {
      const anchorButton = overlay.querySelector(`[data-face-id="${anchor.id}"]`);
      expect(anchorButton?.getAttribute('aria-label')).toContain(guidedCopy('names.no_score.public'));
      expect(anchorButton?.textContent).not.toMatch(/\d+\s*%/);
    }
  });
});
