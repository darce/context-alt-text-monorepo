import React from 'react';
import { __ } from '@wordpress/i18n';
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../components/ui/dialog';

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  description: React.ReactNode;
  confirmLabel: string;
  isPending?: boolean;
}

export const ConfirmDialog = ({
  open,
  onOpenChange,
  onConfirm,
  onCancel,
  title,
  description,
  confirmLabel,
  isPending = false,
}: ConfirmDialogProps): React.JSX.Element => (
  <DialogRoot open={open} onOpenChange={onOpenChange}>
    <DialogPortal>
      <DialogOverlay />
      <DialogContent>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        <div className="acx-dialog__actions">
          <button type="button" className="acx-button acx-button--secondary" onClick={onCancel} disabled={isPending}>
            {__('Cancel', 'alt-context')}
          </button>
          <button type="button" className="acx-button acx-button--danger" onClick={onConfirm} disabled={isPending}>
            {isPending ? __('Processing...', 'alt-context') : confirmLabel}
          </button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
);
