/**
 * Hook for handling confirmation dialog state and copy.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';

export type SaveDialogAction = 'rename' | 'merge' | 'assign' | 'create';

interface ConfirmDialogState {
  open: boolean;
  action: SaveDialogAction;
  label: string;
}

export interface ConfirmDialogCopy {
  title: string;
  description: string;
  confirmLabel: string;
}

export const useClusterConfirmDialog = () => {
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState | null>(null);
  const confirmResolverRef = useRef<((confirmed: boolean) => void) | null>(null);

  const resolveConfirmDialog = useCallback((confirmed: boolean) => {
    const resolver = confirmResolverRef.current;
    confirmResolverRef.current = null;
    setConfirmDialog(null);
    if (resolver) {
      resolver(confirmed);
    }
  }, []);

  const requestConfirm = useCallback((action: SaveDialogAction, label: string) => {
    return new Promise<boolean>((resolve) => {
      confirmResolverRef.current = resolve;
      setConfirmDialog({ open: true, action, label });
    });
  }, []);

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open) {
        resolveConfirmDialog(false);
      }
    },
    [resolveConfirmDialog],
  );

  const handleConfirm = useCallback(() => {
    resolveConfirmDialog(true);
  }, [resolveConfirmDialog]);

  const handleCancel = useCallback(() => {
    resolveConfirmDialog(false);
  }, [resolveConfirmDialog]);

  useEffect(
    () => () => {
      if (confirmResolverRef.current) {
        confirmResolverRef.current(false);
        confirmResolverRef.current = null;
      }
    },
    [],
  );

  const confirmDialogCopy = useMemo<ConfirmDialogCopy | null>(() => {
    if (!confirmDialog) {
      return null;
    }

    const fallbackLabel = __('this cluster', 'alt-context');
    const labelText = confirmDialog.label || fallbackLabel;
    const isAssign = confirmDialog.action === 'assign';
    return {
      title: isAssign ? __('Assign identity', 'alt-context') : __('Confirm merge', 'alt-context'),
      description: isAssign
        ? sprintf(__('Assign this identity to "%s"?', 'alt-context'), labelText)
        : sprintf(__('Merge this cluster into existing "%s"?', 'alt-context'), labelText),
      confirmLabel: isAssign ? __('Assign', 'alt-context') : __('Merge', 'alt-context'),
    };
  }, [confirmDialog]);

  return {
    confirmDialog,
    confirmDialogCopy,
    requestConfirm,
    handleOpenChange,
    handleConfirm,
    handleCancel,
  };
};
