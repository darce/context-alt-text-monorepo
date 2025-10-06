import React from "react";

import { __ } from "@wordpress/i18n";

import { Button } from "@/components/ui/button";

export interface RecognitionActionsProps {
    selectionCount: number;
    disabled?: boolean;
    onTriggerRecognition?: () => void;
}

export const RecognitionActions = ({ selectionCount, disabled, onTriggerRecognition }: RecognitionActionsProps): React.JSX.Element => {
    return (
        <section
            className="cat-workbench__panel"
            aria-label={__("Recognition actions", "context-alt-text")}
        >
            <header>
                <h2>{__("Recognition", "context-alt-text")}</h2>
                <p>
                    {__("Run face and brand detection to enrich context for selected items.", "context-alt-text")}
                </p>
            </header>
            <Button
                variant="default"
                size="md"
                onClick={onTriggerRecognition}
                disabled={disabled || selectionCount === 0}
            >
                {__("Trigger Recognition", "context-alt-text")}
            </Button>
            <small>
                {__(
                    "Analytics event `cat_workbench_recognition_triggered` will fire once this button is connected to the service layer.",
                    "context-alt-text",
                )}
            </small>
        </section>
    );
};
