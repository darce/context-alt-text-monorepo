import React from "react";

import { __ } from "@wordpress/i18n";

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
        <section className="cat-workbench__panel" aria-label={__("Bulk alt text authoring", "context-alt-text")}>
            <header>
                <h2>{__("Bulk Alt Text", "context-alt-text")}</h2>
                <p>
                    {__(
                        "Draft or publish descriptions for the selected media items. AI generation becomes available once the feature flag and service bindings are active.",
                        "context-alt-text",
                    )}
                </p>
            </header>
            <div className="cat-workbench__panel-actions">
                <Button
                    variant="primary"
                    size="md"
                    onClick={onGenerateDrafts}
                    disabled={!hasSelection || !enableGeneration}
                >
                    {__("Generate Drafts", "context-alt-text")}
                </Button>
                <Button variant="default" size="md" onClick={onPublishDrafts} disabled={!hasSelection}>
                    {__("Publish Drafts", "context-alt-text")}
                </Button>
            </div>
            <div className="cat-workbench__panel-body">
                <textarea
                    className="cat-workbench__textarea"
                    placeholder={
                        enableGeneration
                            ? __("Draft alt text will appear here once hooked up to the API.", "context-alt-text")
                            : __("Enable the Workbench AI feature flag to unlock draft generation.", "context-alt-text")
                    }
                    rows={6}
                    disabled
                />
                <small>
                    {__(
                        "Selection-based drafting will unlock after hooking into `/wp-json/cat/v1/alt-text/bulk` and adding auto-save.",
                        "context-alt-text",
                    )}
                </small>
            </div>
        </section>
    );
};
