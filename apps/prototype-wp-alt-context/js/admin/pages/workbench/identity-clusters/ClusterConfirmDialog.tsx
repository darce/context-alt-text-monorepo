import React from 'react';
import { __ } from '@wordpress/i18n';

import type { ConfirmDialogCopy } from './useClusterConfirmDialog';
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../../components/ui/dialog';

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
    <DialogRoot open={dialog.open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogContent>
          <div className="acx-queue-modal">
            <DialogTitle>{copy.title}</DialogTitle>
            <DialogDescription>{copy.description}</DialogDescription>
            <div className="acx-queue-modal__actions">
              <button type="button" className="button" onClick={onCancel}>
                {__('Cancel', 'alt-context')}
              </button>
              <button type="button" className="button button-primary" onClick={onConfirm}>
                {copy.confirmLabel}
              </button>
            </div>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};
