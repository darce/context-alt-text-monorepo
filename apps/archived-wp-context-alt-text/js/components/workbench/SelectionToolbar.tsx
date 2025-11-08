import React from "react";

import { __, _n } from "@wordpress/i18n";

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
    const selectionLabel = _n("item selected", "items selected", selectionCount, "context-alt-text");

    return (
        <header className="cat-workbench__toolbar" aria-live="polite">
            <div>
                <strong>{selectionCount}</strong> {selectionLabel}
            </div>
            <div className="cat-workbench__toolbar-actions">
                <Button variant="primary" size="sm" onClick={onGenerate} disabled={!hasSelection}>
                    {__("Generate Alt Text", "context-alt-text")}
                </Button>
                <Button variant="default" size="sm" onClick={onRegenerate} disabled={!hasSelection}>
                    {__("Regenerate", "context-alt-text")}
                </Button>
                <Button variant="default" size="sm" onClick={onMarkReviewed} disabled={!hasSelection}>
                    {__("Mark Reviewed", "context-alt-text")}
                </Button>
                <Button variant="subtle" size="sm" onClick={onClearSelection} disabled={!hasSelection}>
                    {__("Clear Selection", "context-alt-text")}
                </Button>
            </div>
        </header>
    );
};
