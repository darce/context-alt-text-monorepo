import React from 'react';

import type { ConfirmDialogCopy } from './useClusterConfirmDialog';
import { ConfirmDialog } from '../../../components/ui/ConfirmDialog';

interface ClusterConfirmDialogProps {
  dialog: { open: boolean } | null;
  copy: ConfirmDialogCopy | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ClusterConfirmDialog = ({
  dialog,
  copy,
  onOpenChange,
  onConfirm,
  onCancel,
}: ClusterConfirmDialogProps): React.JSX.Element | null => {
  if (!dialog || !copy) {
    return null;
  }

  return (
    <ConfirmDialog
      open={dialog.open}
      onOpenChange={onOpenChange}
      onConfirm={onConfirm}
      onCancel={onCancel}
      title={copy.title}
      description={copy.description}
      confirmLabel={copy.confirmLabel}
    />
  );
};
