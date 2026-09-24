import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { overlayRectFor } from '../../../../components/ui/faceGeometry';
import { guidedCopy } from '../../../guidedPrototype/publicGuideCopy';
import { GuidedFaceOverlay, type GuidedFaceOverlayFace } from '../GuidedFaceOverlay';

const naturalSize = { width: 1000, height: 800 };

const faces: GuidedFaceOverlayFace[] = [
  {
    id: 'katy',
    box: { x: 100, y: 80, width: 220, height: 300 },
    label: 'Katy Perry',
    similarityText: '56.7% (weak)',
    strength: 'weak',
  },
  {
    id: 'justin',
    box: { x: 500, y: 120, width: 180, height: 260 },
    label: 'Justin Trudeau',
    similarityText: '91.2% (strong)',
    strength: 'strong',
  },
];

const matchWords = (face: GuidedFaceOverlayFace): string =>
  face.strength === 'weak' ? guidedCopy('names.weak.public') : guidedCopy('names.strong.public');

const accessibleName = (face: GuidedFaceOverlayFace): string => `${face.label}, ${matchWords(face)}`;

describe('GuidedFaceOverlay', () => {
  it('renders one positioned outline button per face with strength words instead of similarity values', () => {
    render(<GuidedFaceOverlay faces={faces} naturalSize={naturalSize} visible idPrefix="guided-tribeca" />);

    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(faces.length);

    faces.forEach((face) => {
      const button = screen.getByRole('button', {
        name: accessibleName(face),
      });
      const rect = overlayRectFor(face.box, naturalSize);

      expect(button).toHaveClass('acx-guided-face-overlay__outline');
      expect(button).toHaveAttribute('id', `guided-tribeca-face-${face.id}`);
      expect(button).toHaveStyle({
        left: `${rect.left}%`,
        top: `${rect.top}%`,
        width: `${rect.width}%`,
        height: `${rect.height}%`,
      });
      expect(button).toHaveTextContent(`${face.label} · ${matchWords(face)}`);
      expect(button.textContent).not.toMatch(/\d+(?:\.\d+)?%/);
    });
  });

  it('uses the warning icon and dashed outline only for weak matches', () => {
    render(<GuidedFaceOverlay faces={faces} naturalSize={naturalSize} visible idPrefix="guided-tribeca" />);

    const weakButton = screen.getByRole('button', { name: accessibleName(faces[0]) });
    const strongButton = screen.getByRole('button', { name: accessibleName(faces[1]) });

    expect(weakButton).toHaveClass('acx-guided-face-overlay__outline--weak');
    expect(weakButton).toHaveClass('acx-guided-face-overlay__outline');
    expect(weakButton.querySelector('.acx-guided-face-overlay__warning-icon')).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Weak match' })).toBeInTheDocument();
    expect(strongButton).not.toHaveClass('acx-guided-face-overlay__outline--weak');
    expect(strongButton.querySelector('.acx-guided-face-overlay__warning-icon')).toBeNull();
  });

  it('uses the no-score copy for a cluster anchor', () => {
    const anchor: GuidedFaceOverlayFace = {
      ...faces[1],
      id: 'anchor',
      strength: 'self_anchor',
      isClusterAnchor: true,
    };
    render(<GuidedFaceOverlay faces={[anchor]} naturalSize={naturalSize} visible idPrefix="guided-tribeca" />);

    const noScoreCopy = `${guidedCopy('names.no_score.public')} Compare photos before you use this name.`;
    const button = screen.getByRole('button', { name: `${anchor.label}, ${noScoreCopy}` });
    expect(button).toHaveTextContent(noScoreCopy);
    expect(button).not.toHaveTextContent(/\d+(?:\.\d+)?%/);
    expect(button.querySelector('.acx-guided-face-overlay__warning-icon')).toBeNull();
  });

  it('keeps every face button in the keyboard sequence and clears highlight on Escape', async () => {
    const user = userEvent.setup();
    const onHighlightChange = vi.fn();
    render(
      <GuidedFaceOverlay
        faces={faces}
        naturalSize={naturalSize}
        visible
        idPrefix="guided-tribeca"
        onHighlightChange={onHighlightChange}
      />,
    );

    const buttons = screen.getAllByRole('button');
    await user.tab();
    expect(document.activeElement).toBe(buttons[0]);
    await user.tab();
    expect(document.activeElement).toBe(buttons[1]);

    await user.keyboard('{Escape}');
    expect(onHighlightChange).toHaveBeenLastCalledWith(null);
  });

  it('keeps hidden-state face buttons queryable and focusable', () => {
    render(<GuidedFaceOverlay faces={faces} naturalSize={naturalSize} visible={false} idPrefix="guided-tribeca" />);

    const layer = screen.getByTestId('guided-face-overlay');
    const buttons = faces.map((face) => screen.getByRole('button', { name: accessibleName(face) }));
    expect(layer).not.toHaveAttribute('hidden');
    expect(buttons).toHaveLength(faces.length);
    expect(layer.querySelectorAll('[aria-hidden="true"]')).toHaveLength(1);
    buttons.forEach((button) => {
      expect(button).not.toHaveAttribute('hidden');
      expect(button).toHaveAttribute('tabindex', '0');
      button.focus();
      expect(button).toHaveFocus();
    });
  });

  it(
    'pins a face on click, keeps it highlighted after pointer-leave and blur, and unpins on a second click',
    async () => {
      const user = userEvent.setup();
      const onHighlightChange = vi.fn();
      render(
        <GuidedFaceOverlay
          faces={[faces[0]]}
          naturalSize={naturalSize}
          visible
          idPrefix="guided-tribeca"
          onHighlightChange={onHighlightChange}
        />,
      );

      const button = screen.getByRole('button', { name: accessibleName(faces[0]) });
      await user.click(button);
      expect(onHighlightChange).toHaveBeenLastCalledWith('katy');
      expect(button).toHaveAttribute('aria-pressed', 'true');
      expect(button).toHaveAttribute('data-pinned', 'true');
      expect(button).toHaveClass('acx-guided-face-overlay__outline--pinned');

      fireEvent.pointerLeave(button);
      fireEvent.blur(button);
      expect(onHighlightChange).toHaveBeenLastCalledWith('katy');
      expect(button).toHaveAttribute('data-pinned', 'true');
      expect(button).toHaveClass('acx-guided-face-overlay__outline--pinned');

      await user.click(button);
      expect(button).toHaveAttribute('aria-pressed', 'false');
      expect(button).toHaveAttribute('data-pinned', 'false');
      expect(button).not.toHaveClass('acx-guided-face-overlay__outline--pinned');
    },
  );

  it('clears a pinned face and the interaction highlight on Escape', async () => {
    const user = userEvent.setup();
    const onHighlightChange = vi.fn();
    render(
      <GuidedFaceOverlay
        faces={[faces[0]]}
        naturalSize={naturalSize}
        visible
        idPrefix="guided-tribeca"
        onHighlightChange={onHighlightChange}
      />,
    );

    const button = screen.getByRole('button', { name: accessibleName(faces[0]) });
    await user.click(button);
    await user.keyboard('{Escape}');

    expect(button).toHaveAttribute('aria-pressed', 'false');
    expect(button).toHaveAttribute('data-pinned', 'false');
    expect(button).not.toHaveClass('acx-guided-face-overlay__outline--pinned');
    expect(button).not.toHaveClass('acx-guided-face-overlay__outline--highlighted');
    expect(onHighlightChange).toHaveBeenLastCalledWith(null);
  });

  it('supports pointer highlighting without changing the accessible button name or pressed state', () => {
    const onHighlightChange = vi.fn();
    render(
      <GuidedFaceOverlay
        faces={[faces[0]]}
        naturalSize={naturalSize}
        visible
        idPrefix="guided-tribeca"
        onHighlightChange={onHighlightChange}
      />,
    );

    const button = screen.getByRole('button', { name: accessibleName(faces[0]) });
    fireEvent.pointerEnter(button);
    expect(onHighlightChange).toHaveBeenCalledWith('katy');
    expect(button).toHaveAttribute('aria-pressed', 'false');
    expect(button).toHaveAttribute('data-pinned', 'false');
    fireEvent.pointerLeave(button);
    expect(onHighlightChange).toHaveBeenLastCalledWith(null);
  });
});
