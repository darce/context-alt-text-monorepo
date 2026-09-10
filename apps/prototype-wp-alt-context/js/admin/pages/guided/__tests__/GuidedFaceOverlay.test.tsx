import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { overlayRectFor } from '../../../../components/ui/faceGeometry';
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

describe('GuidedFaceOverlay', () => {
  it('renders one percent-positioned outline button and chip per face', () => {
    render(<GuidedFaceOverlay faces={faces} naturalSize={naturalSize} visible idPrefix="guided-tribeca" />);

    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(faces.length);

    faces.forEach((face) => {
      const button = screen.getByRole('button', {
        name: `${face.label}, ${face.similarityText}`,
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
      expect(button).toHaveTextContent(`${face.label} · ${face.similarityText}`);
    });
  });

  it('uses the warning icon and dashed outline only for weak matches', () => {
    render(<GuidedFaceOverlay faces={faces} naturalSize={naturalSize} visible idPrefix="guided-tribeca" />);

    const weakButton = screen.getByRole('button', { name: 'Katy Perry, 56.7% (weak)' });
    const strongButton = screen.getByRole('button', { name: 'Justin Trudeau, 91.2% (strong)' });

    expect(weakButton).toHaveClass('acx-guided-face-overlay__outline--weak');
    expect(weakButton).toHaveClass('acx-guided-face-overlay__outline');
    expect(weakButton.querySelector('.acx-guided-face-overlay__warning-icon')).toBeTruthy();
    expect(strongButton).not.toHaveClass('acx-guided-face-overlay__outline--weak');
    expect(strongButton.querySelector('.acx-guided-face-overlay__warning-icon')).toBeNull();
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

  it('marks the layer hidden while retaining its face buttons in the DOM and tab order', () => {
    render(<GuidedFaceOverlay faces={faces} naturalSize={naturalSize} visible={false} idPrefix="guided-tribeca" />);

    const layer = screen.getByTestId('guided-face-overlay');
    const buttons = Array.from(layer.querySelectorAll('button'));
    expect(layer).toHaveAttribute('hidden');
    expect(buttons).toHaveLength(faces.length);
    expect(layer.querySelectorAll('[aria-hidden="true"]')).toHaveLength(1);
    buttons.forEach((button) => {
      expect(button).not.toHaveAttribute('hidden');
      expect(button).toHaveAttribute('tabindex', '0');
    });
  });

  it('supports pointer highlighting without changing the accessible button name', () => {
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

    const button = screen.getByRole('button', { name: 'Katy Perry, 56.7% (weak)' });
    fireEvent.pointerEnter(button);
    expect(onHighlightChange).toHaveBeenCalledWith('katy');
    expect(button).toHaveAttribute('aria-pressed', 'true');
    fireEvent.pointerLeave(button);
    expect(onHighlightChange).toHaveBeenLastCalledWith(null);
  });
});
