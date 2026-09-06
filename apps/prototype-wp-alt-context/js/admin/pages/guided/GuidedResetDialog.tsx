import React, { useEffect, useRef, useState } from 'react';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../components/ui/dialog';
import { focusGuidedSection } from './GuidedPrototypeGuide';

export interface GuidedResetDialogProps {
  onConfirm: () => void;
}

export const GuidedResetDialog = ({ onConfirm }: GuidedResetDialogProps): React.JSX.Element => {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const focusScenarioAfterConfirmRef = useRef(false);
  const wasOpenRef = useRef(false);

  const handleOpen = (): void => {
    setOpen(true);
  };

  const handleCancel = (): void => {
    setOpen(false);
  };

  const handleConfirm = (): void => {
    focusScenarioAfterConfirmRef.current = true;
    onConfirm();
    setOpen(false);
  };

  useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      return;
    }

    if (!wasOpenRef.current) {
      return;
    }

    wasOpenRef.current = false;
    if (focusScenarioAfterConfirmRef.current) {
      focusScenarioAfterConfirmRef.current = false;
      focusGuidedSection('understand');
      return;
    }

    triggerRef.current?.focus();
  }, [open]);

  const handleCloseAutoFocus = (event: Event): void => {
    event.preventDefault();
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="acx-button acx-button--tertiary"
        onClick={handleOpen}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        Reset practice
      </button>
      <DialogRoot open={open} onOpenChange={setOpen}>
        <DialogPortal>
          <DialogOverlay />
          <DialogContent onCloseAutoFocus={handleCloseAutoFocus}>
            <DialogTitle>Reset this practice?</DialogTitle>
            <DialogDescription>
              This removes your practice changes. The real WordPress image is not touched.
            </DialogDescription>
            <div className="acx-dialog__actions">
              <button type="button" className="acx-button acx-button--secondary" onClick={handleCancel} autoFocus>
                Cancel
              </button>
              <button type="button" className="acx-button acx-button--danger" onClick={handleConfirm}>
                Reset practice
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </>
  );
};

GuidedResetDialog.displayName = 'GuidedResetDialog';
