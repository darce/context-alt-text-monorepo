import { __, _n, sprintf } from '@wordpress/i18n';
import { useCallback, useState } from 'react';

type ConfirmAction = 'merge' | 'dismiss' | null;

interface SelectionState {
  selectedIds: Set<string>;
  count: number;
}

interface ClusterIdsPayload {
  clusterIds: string[];
}

interface AsyncMutation {
  isPending: boolean;
  mutateAsync: (payload: ClusterIdsPayload) => Promise<unknown>;
}

interface UseRosterBulkConfirmationOptions {
  selection: SelectionState;
  bulkMergeMutation: AsyncMutation;
  bulkDismissMutation: AsyncMutation;
}

export const useRosterBulkConfirmation = ({
  selection,
  bulkMergeMutation,
  bulkDismissMutation,
}: UseRosterBulkConfirmationOptions) => {
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);

  const handleBulkMerge = useCallback(() => {
    if (selection.selectedIds.size >= 2) {
      setConfirmAction('merge');
    }
  }, [selection.selectedIds]);

  const handleBulkDismiss = useCallback(() => {
    if (selection.selectedIds.size > 0) {
      setConfirmAction('dismiss');
    }
  }, [selection.selectedIds]);

  const handleConfirm = useCallback(() => {
    const ids = Array.from(selection.selectedIds);
    void (async () => {
      let shouldClose = false;
      try {
        if (confirmAction === 'merge') {
          await bulkMergeMutation.mutateAsync({ clusterIds: ids });
          shouldClose = true;
        } else if (confirmAction === 'dismiss') {
          await bulkDismissMutation.mutateAsync({ clusterIds: ids });
          shouldClose = true;
        }
      } catch {
        return;
      } finally {
        if (shouldClose) {
          setConfirmAction(null);
        }
      }
    })();
  }, [bulkDismissMutation, bulkMergeMutation, confirmAction, selection.selectedIds]);

  const handleConfirmOpenChange = useCallback((open: boolean) => {
    if (!open) {
      setConfirmAction(null);
    }
  }, []);

  // Confirm labels stay short ("Merge"/"Dismiss") so they differ from the bar's
  // "Merge N clusters" accessible names — dialog description carries count+object.
  // Descriptions use _n so translators with >2 plural forms can select correctly.
  const confirmDialogCopy =
    confirmAction === 'merge'
      ? {
          title: __('Confirm merge', 'alt-context'),
          description: sprintf(
            // translators: %d: number of selected clusters to merge
            _n(
              'Are you sure you want to merge %d cluster? This action cannot be undone.',
              'Are you sure you want to merge %d clusters? This action cannot be undone.',
              selection.count,
              'alt-context',
            ),
            selection.count,
          ),
          confirmLabel: __('Merge', 'alt-context'),
        }
      : confirmAction === 'dismiss'
        ? {
            title: __('Confirm dismiss', 'alt-context'),
            description: sprintf(
              // translators: %d: number of selected clusters to dismiss
              _n(
                'Are you sure you want to dismiss %d cluster?',
                'Are you sure you want to dismiss %d clusters?',
                selection.count,
                'alt-context',
              ),
              selection.count,
            ),
            confirmLabel: __('Dismiss', 'alt-context'),
          }
        : null;

  return {
    confirmAction,
    setConfirmAction,
    handleBulkMerge,
    handleBulkDismiss,
    handleConfirm,
    handleConfirmOpenChange,
    confirmDialogCopy,
  };
};
