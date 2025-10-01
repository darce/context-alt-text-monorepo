import React from "react";

import { Button } from "@/components/ui/button";

export interface BulkAltTextPanelProps {
    selectionCount: number;
    onGenerateDrafts?: () => void;
    onPublishDrafts?: () => void;
    enableGeneration?: boolean;
}

export const BulkAltTextPanel = ({
    selectionCount,
    onGenerateDrafts,
    onPublishDrafts,
    enableGeneration = false,
}: BulkAltTextPanelProps): React.JSX.Element => {
    const hasSelection = selectionCount > 0;

    return (
        <section className="cat-workbench__panel" aria-label="Bulk alt text authoring">
            <header>
                <h2>Bulk Alt Text</h2>
                <p>
                    Draft or publish descriptions for the selected media items. AI generation becomes available once the
                    feature flag and service bindings are active.
                </p>
            </header>
            <div className="cat-workbench__panel-actions">
                <Button
                    variant="primary"
                    size="md"
                    onClick={onGenerateDrafts}
                    disabled={!hasSelection || !enableGeneration}
                >
                    Generate Drafts
                </Button>
                <Button variant="default" size="md" onClick={onPublishDrafts} disabled={!hasSelection}>
                    Publish Drafts
                </Button>
            </div>
            <div className="cat-workbench__panel-body">
                <textarea
                    className="cat-workbench__textarea"
                    placeholder={
                        enableGeneration
                            ? "Draft alt text will appear here once hooked up to the API."
                            : "Enable the Workbench AI feature flag to unlock draft generation."
                    }
                    rows={6}
                    disabled
                />
                <small>
                    Selection-based drafting will unlock after hooking into `/wp-json/cat/v1/alt-text/bulk` and adding auto-save.
                </small>
            </div>
        </section>
    );
};
