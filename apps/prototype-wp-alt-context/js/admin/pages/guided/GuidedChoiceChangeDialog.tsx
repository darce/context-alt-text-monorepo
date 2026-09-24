import React, { useRef } from 'react';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../components/ui/dialog';
import { guidedCopy } from '../../guidedPrototype/publicGuideCopy';

export interface GuidedChoiceChangeDialogProps {
  open: boolean;
  onChangeName: () => void;
  onKeepEdits: () => void;
}

export const GuidedChoiceChangeDialog = ({
  open,
  onChangeName,
  onKeepEdits,
}: GuidedChoiceChangeDialogProps): React.JSX.Element => {
  const keepEditsRef = useRef<HTMLButtonElement>(null);

  return (
    <DialogRoot
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          onKeepEdits();
        }
      }}
    >
      <DialogPortal>
        <DialogOverlay />
        <DialogContent
          aria-modal="true"
          className="acx-guided-choice-change-dialog"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            keepEditsRef.current?.focus();
          }}
        >
          <DialogTitle>{guidedCopy('name_change.title.public')}</DialogTitle>
          <DialogDescription>{guidedCopy('name_change.body.public')}</DialogDescription>
          <div className="acx-dialog__actions">
            <button
              ref={keepEditsRef}
              type="button"
              className="acx-button acx-button--primary"
              onClick={onKeepEdits}
            >
              {guidedCopy('name_change.keep.public')}
            </button>
            <button type="button" className="acx-button acx-button--secondary" onClick={onChangeName}>
              {guidedCopy('name_change.confirm.public')}
            </button>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};

GuidedChoiceChangeDialog.displayName = 'GuidedChoiceChangeDialog';
