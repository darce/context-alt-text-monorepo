import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { FaceThumbnail } from '../FaceThumbnail';
import type { ClusterFace } from '../../api/recognitionApi';

const face: ClusterFace = {
  id: 'face-1',
  media_id: 100,
  similarity: 0.5,
  confidence: 0.8,
  bbox: { x: 0, y: 0, width: 20, height: 40 },
};

describe('FaceThumbnail', () => {
  it('renders placeholder when no metadata is available', () => {
    const { container } = render(<FaceThumbnail face={face} size={64} />);
    expect(container.querySelector('.acx-cluster-card__face--placeholder')).toBeInTheDocument();
  });

  it('calls onClick when provided', async () => {
    const onClick = vi.fn();
    render(<FaceThumbnail face={face} mediaMeta={{ url: 'https://example.com/1.jpg' }} onClick={onClick} />);
    const thumb = screen.getByRole('img');
    await userEvent.click(thumb);
    expect(onClick).toHaveBeenCalled();
  });
});
