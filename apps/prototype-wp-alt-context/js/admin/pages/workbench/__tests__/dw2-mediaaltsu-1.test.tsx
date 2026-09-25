import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { correctDescriptionHistoryItem } from '../../../api/describeApi';
import type { DescriptionHistoryItem } from '../../../api/describeApi';
import { MediaAltSuggest, UNMARK_DECORATIVE_LABEL } from '../MediaAltSuggest';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _position, explicitIndex) =>
      String(args[explicitIndex ? Number(explicitIndex) - 1 : index++] ?? ''),
    );
  },
}));

vi.mock('../../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../../api/describeApi')>(
    '../../../api/describeApi',
  );
  return { ...actual, correctDescriptionHistoryItem: vi.fn() };
});

const correctMock = vi.mocked(correctDescriptionHistoryItem);

const renderSuggest = (element: ReactElement, client: QueryClient) =>
  render(<QueryClientProvider client={client}>{element}</QueryClientProvider>);

describe('dw2-mediaaltsu-1', () => {
  it('keeps the unmark row identity and state coherent if isDecorative flips while busy', async () => {
    let resolveCorrect!: (value: DescriptionHistoryItem) => void;
    correctMock.mockReturnValue(
      new Promise<DescriptionHistoryItem>((resolve) => {
        resolveCorrect = resolve;
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const title = 'Bridge';
    const { rerender } = renderSuggest(
      <MediaAltSuggest isDecorative mediaId={42} committedAlt={null} title={title} />,
      client,
    );

    fireEvent.click(screen.getByRole('button', { name: `Decorative: ${title}`, pressed: true }));
    const busyButton = await screen.findByRole('button', {
      name: `Removing decorative mark for ${title}…`,
    });
    expect(busyButton).toBeDisabled();

    rerender(
      <QueryClientProvider client={client}>
        <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt={null} title={title} />
      </QueryClientProvider>,
    );

    expect(busyButton).toHaveAttribute('aria-pressed', 'true');
    expect(busyButton).toHaveAttribute('title', UNMARK_DECORATIVE_LABEL);
    const descriptionId = busyButton.getAttribute('aria-describedby');
    expect(descriptionId).toBeTruthy();
    expect(document.getElementById(descriptionId!)).toHaveTextContent(UNMARK_DECORATIVE_LABEL);
    expect(busyButton).toHaveAttribute('aria-label', `Removing decorative mark for ${title}…`);

    await act(async () => {
      resolveCorrect({ current_alt_text: '', is_decorative: false } as DescriptionHistoryItem);
    });
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
  });
});
