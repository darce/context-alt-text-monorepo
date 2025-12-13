import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { IdentityThumbnail } from '../IdentityThumbnail';
import type { ClusterIdentity } from '../../../api/recognition';

const identity: ClusterIdentity = {
  identity_id: 'identity-1',
  media_id: 100,
  similarity: 0.5,
  confidence: 0.8,
  bbox: { x: 0, y: 0, width: 20, height: 40 },
};

describe('IdentityThumbnail', () => {
  it('renders placeholder when no metadata is available', () => {
    const { container } = render(<IdentityThumbnail identity={identity} size={64} />);
    expect(container.querySelector('.acx-cluster-card__face--placeholder')).toBeInTheDocument();
  });

  it('uses backend-provided thumbnail when available', () => {
    render(<IdentityThumbnail identity={{ ...identity, thumbnail_url: 'https://example.com/thumb.jpg' }} size={96} />);
    const image = screen.getByRole('img');
    expect(image).toHaveAttribute('src', 'https://example.com/thumb.jpg');
  });

  it('calls onClick when provided', async () => {
    const onClick = vi.fn();
    render(
      <IdentityThumbnail identity={identity} mediaMeta={{ url: 'https://example.com/1.jpg' }} onClick={onClick} />,
    );
    const thumb = screen.getByRole('img');
    await userEvent.click(thumb);
    expect(onClick).toHaveBeenCalled();
  });
});
