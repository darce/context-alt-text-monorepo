import React from "react";

import { Button } from "@/components/ui/button";

export interface RecognitionActionsProps {
    selectionCount: number;
    disabled?: boolean;
    onTriggerRecognition?: () => void;
}

export const RecognitionActions = ({ selectionCount, disabled, onTriggerRecognition }: RecognitionActionsProps): React.JSX.Element => {
    return (
        <section className="cat-workbench__panel" aria-label="Recognition actions">
            <header>
                <h2>Recognition</h2>
                <p>Run face and brand detection to enrich context for selected items.</p>
            </header>
            <Button
                variant="default"
                size="md"
                onClick={onTriggerRecognition}
                disabled={disabled || selectionCount === 0}
            >
                Trigger Recognition
            </Button>
            <small>
                Analytics event `cat_workbench_recognition_triggered` will fire once this button is connected to the service layer.
            </small>
        </section>
    );
};
