import React, { useEffect, useRef, useState } from 'react';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../components/ui/dialog';
import { guidedCopy } from '../../guidedPrototype/copy';
import { GUIDED_STEP } from '../../guidedPrototype/state';
import { focusGuidedSection } from './GuidedPrototypeGuide';

export interface GuidedResetDialogProps {
  liveWaiting: boolean;
  onConfirm: () => void;
}

export const GuidedResetDialog = ({ liveWaiting, onConfirm }: GuidedResetDialogProps): React.JSX.Element => {
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
      focusGuidedSection(GUIDED_STEP.CONTEXT);
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
        {guidedCopy('page.reset')}
      </button>
      <DialogRoot open={open} onOpenChange={setOpen}>
        <DialogPortal>
          <DialogOverlay />
          <DialogContent aria-modal="true" onCloseAutoFocus={handleCloseAutoFocus}>
            <DialogTitle>{guidedCopy('reset.title')}</DialogTitle>
            <DialogDescription>{guidedCopy('reset.body')}</DialogDescription>
            {liveWaiting ? <p>{guidedCopy('reset.active_live_note')}</p> : null}
            <div className="acx-dialog__actions">
              <button type="button" className="acx-button acx-button--secondary" onClick={handleCancel} autoFocus>
                {guidedCopy('reset.cancel')}
              </button>
              <button type="button" className="acx-button acx-button--danger" onClick={handleConfirm}>
                {guidedCopy('reset.confirm')}
              </button>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>
    </>
  );
};

GuidedResetDialog.displayName = 'GuidedResetDialog';
