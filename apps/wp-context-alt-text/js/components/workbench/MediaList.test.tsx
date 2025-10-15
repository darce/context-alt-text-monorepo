import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'vitest-axe';
import { MediaList } from './MediaList';
import type { WorkbenchMediaItem } from './WorkbenchApp';

const mockItems: WorkbenchMediaItem[] = [
    {
        id: '1',
        title: 'First image',
        status: 'missing',
        altText: '',
        mimeType: 'image/jpeg',
        updatedAt: '2025-10-01T10:00:00Z',
        thumbnailUrl: 'https://example.com/thumb1.jpg',
        editUrl: '/wp-admin/post.php?post=1&action=edit',
        dimensions: { width: 1920, height: 1080 },
    },
    {
        id: '2',
        title: 'Second image',
        status: 'missing',
        altText: '',
        mimeType: 'image/jpeg',
        updatedAt: '2025-09-30T14:30:00Z',
        thumbnailUrl: 'https://example.com/thumb2.jpg',
        editUrl: '/wp-admin/post.php?post=2&action=edit',
        dimensions: { width: 800, height: 600 },
    },
];

describe('MediaList', () => {
    it('renders empty state when no items provided', () => {
        render(
            <MediaList
                items={[]}
                selectedIds={new Set()}
                onToggleSelect={vi.fn()}
                viewMode="list"
            />
        );

        expect(screen.getByRole('status')).toBeInTheDocument();
        expect(screen.getByText(/no media requires attention right now/i)).toBeInTheDocument();
    });

    it('renders list view with items', () => {
        render(
            <MediaList
                items={mockItems}
                selectedIds={new Set()}
                onToggleSelect={vi.fn()}
                viewMode="list"
            />
        );

        const table = screen.getByRole('table', { name: /media queue/i });
        expect(table).toBeInTheDocument();
        expect(table).toHaveClass('cat-workbench__table--list');

        // Check that both items are rendered
        expect(screen.getByText('First image')).toBeInTheDocument();
        expect(screen.getByText('Second image')).toBeInTheDocument();
    });

    it('renders grid view with items', () => {
        render(
            <MediaList
                items={mockItems}
                selectedIds={new Set()}
                onToggleSelect={vi.fn()}
                viewMode="grid"
            />
        );

        const table = screen.getByRole('table', { name: /media queue/i });
        expect(table).toHaveClass('cat-workbench__table--grid');
    });

    it('displays correct status chips', () => {
        const itemsWithStatuses: WorkbenchMediaItem[] = [
            { ...mockItems[0]!, status: 'missing' },
            { ...mockItems[1]!, status: 'draft' },
        ];

        render(
            <MediaList
                items={itemsWithStatuses}
                selectedIds={new Set()}
                onToggleSelect={vi.fn()}
                viewMode="list"
            />
        );

        expect(screen.getByText('Needs alt text')).toBeInTheDocument();
        expect(screen.getByText('Draft available')).toBeInTheDocument();
    });

    it('handles selection via checkbox', async () => {
        const user = userEvent.setup();
        const onToggleSelect = vi.fn();

        render(
            <MediaList
                items={mockItems}
                selectedIds={new Set()}
                onToggleSelect={onToggleSelect}
                viewMode="list"
            />
        );

        const checkbox = screen.getByRole('checkbox', { name: /select first image/i });
        await user.click(checkbox);

        expect(onToggleSelect).toHaveBeenCalledWith('1');
    });

    it('handles selection via row click', async () => {
        const user = userEvent.setup();
        const onToggleSelect = vi.fn();

        render(
            <MediaList
                items={mockItems}
                selectedIds={new Set()}
                onToggleSelect={onToggleSelect}
                viewMode="list"
            />
        );

        // Find the row containing "First image"
        const rows = screen.getAllByRole('row');
        const targetRow = rows.find(row => within(row).queryByText('First image'));

        if (targetRow) {
            await user.click(targetRow);
            expect(onToggleSelect).toHaveBeenCalledWith('1');
        }
    });

    it('handles selection via keyboard (Space)', async () => {
        const user = userEvent.setup();
        const onToggleSelect = vi.fn();

        render(
            <MediaList
                items={mockItems}
                selectedIds={new Set()}
                onToggleSelect={onToggleSelect}
                viewMode="list"
            />
        );

        const rows = screen.getAllByRole('row');
        const targetRow = rows.find(row => within(row).queryByText('First image'));

        if (targetRow) {
            targetRow.focus();
            await user.keyboard(' ');
            expect(onToggleSelect).toHaveBeenCalledWith('1');
        }
    });

    it('displays selected state correctly', () => {
        render(
            <MediaList
                items={mockItems}
                selectedIds={new Set(['1'])}
                onToggleSelect={vi.fn()}
                viewMode="list"
            />
        );

        const checkbox = screen.getByRole('checkbox', { name: /select first image/i });
        expect(checkbox).toBeChecked();

        const rows = screen.getAllByRole('row');
        const selectedRow = rows.find(row => within(row).queryByText('First image'));
        expect(selectedRow).toHaveAttribute('aria-selected', 'true');
    });

    it('renders recognition metadata when provided', () => {
        const itemsWithRecognition: WorkbenchMediaItem[] = [
            {
                ...mockItems[0]!,
                recognition: {
                    status: "matched",
                    matchedCount: 1,
                    needsReviewCount: 0,
                    matchedRoster: {
                        remoteId: "remote-1",
                        displayName: "Example Person",
                    },
                    updatedAt: 1_700_000_000,
                },
            },
        ];

        render(
            <MediaList
                items={itemsWithRecognition}
                selectedIds={new Set()}
                onToggleSelect={vi.fn()}
                viewMode="list"
            />
        );

        expect(screen.getByText(/Matched 1 recognition \(Example Person\)/i)).toBeInTheDocument();
    });

    it('passes accessibility audit', async () => {
        const { container } = render(
            <MediaList
                items={mockItems}
                selectedIds={new Set()}
                onToggleSelect={vi.fn()}
                viewMode="list"
            />
        );

        const results = await axe(container);
        expect(results.violations).toHaveLength(0);
    });
});
