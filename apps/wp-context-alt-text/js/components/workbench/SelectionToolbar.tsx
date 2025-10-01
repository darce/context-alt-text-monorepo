import React from "react";

import { Button } from "@/components/ui/button";

export interface SelectionToolbarProps {
    selectionCount: number;
    onGenerate?: () => void;
    onRegenerate?: () => void;
    onMarkReviewed?: () => void;
    onClearSelection?: () => void;
}

export const SelectionToolbar = ({
    selectionCount,
    onGenerate,
    onRegenerate,
    onMarkReviewed,
    onClearSelection,
}: SelectionToolbarProps): React.JSX.Element => {
    const hasSelection = selectionCount > 0;

    return (
        <header className="cat-workbench__toolbar" aria-live="polite">
            <div>
                <strong>{selectionCount}</strong> item{selectionCount === 1 ? "" : "s"} selected
            </div>
            <div className="cat-workbench__toolbar-actions">
                <Button variant="primary" size="sm" onClick={onGenerate} disabled={!hasSelection}>
                    Generate Alt Text
                </Button>
                <Button variant="default" size="sm" onClick={onRegenerate} disabled={!hasSelection}>
                    Regenerate
                </Button>
                <Button variant="default" size="sm" onClick={onMarkReviewed} disabled={!hasSelection}>
                    Mark Reviewed
                </Button>
                <Button variant="subtle" size="sm" onClick={onClearSelection} disabled={!hasSelection}>
                    Clear Selection
                </Button>
            </div>
        </header>
    );
};
