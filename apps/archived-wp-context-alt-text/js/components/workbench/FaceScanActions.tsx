import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { __ } from "@wordpress/i18n";

import { Button } from "@/components/ui/button";
import { useFaceScan } from "@/hooks/useFaceScan";

export interface FaceScanActionsProps {
    selectedIds: number[];
    onScanComplete?: (result: { jobId: string; queuedCount: number }) => void;
}

/**
 * Component for triggering face detection scans on selected media items.
 * Provides a button to scan for faces and displays scan status/results.
 */
export const FaceScanActions = ({ selectedIds, onScanComplete }: FaceScanActionsProps): React.JSX.Element => {
    const { scanFaces, isScanning, error, result, reset } = useFaceScan();
    const queryClient = useQueryClient();

    const handleScanClick = React.useCallback(() => {
        if (selectedIds.length === 0) {
            return;
        }

        void scanFaces(selectedIds);
    }, [selectedIds, scanFaces]);

    React.useEffect(() => {
        if (result && onScanComplete) {
            onScanComplete({
                jobId: result.jobId,
                queuedCount: result.queuedCount,
            });
        }
    }, [result, onScanComplete]);

    React.useEffect(() => {
        if (!result) {
            return;
        }

        void (async () => {
            await queryClient.invalidateQueries({
                predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[0] === "unknown-clusters",
            });

            await queryClient.invalidateQueries({
                predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[0] === "cluster-detail",
            });
        })();
    }, [result, queryClient]);

    const isDisabled = selectedIds.length === 0 || isScanning;

    return (
        <section className="cat-workbench__panel" aria-label={__("Face scan actions", "context-alt-text")}>
            <header>
                <h2>{__("Face Clustering", "context-alt-text")}</h2>
                <p>
                    {__(
                        "Scan selected images to detect and group similar faces for efficient labeling.",
                        "context-alt-text",
                    )}
                </p>
            </header>

            <Button variant="default" size="md" onClick={handleScanClick} disabled={isDisabled}>
                {isScanning ? __("Scanning…", "context-alt-text") : __("Scan for Faces", "context-alt-text")}
            </Button>

            <dl className="cat-face-scan__summary" aria-live="polite">
                <div>
                    <dt>{__("Selected items", "context-alt-text")}</dt>
                    <dd>{selectedIds.length}</dd>
                </div>
                {result && (
                    <>
                        <div>
                            <dt>{__("Queued for scanning", "context-alt-text")}</dt>
                            <dd>{result.queuedCount}</dd>
                        </div>
                    </>
                )}
            </dl>

            {!isScanning && result && (
                <p className="cat-face-scan__status cat-face-scan__status--success" role="status" aria-live="polite">
                    {__(
                        `Queued ${result.queuedCount} items for face detection. Job ID: ${result.jobId}. Faces will appear in the Unknown People panel once processing completes.`,
                        "context-alt-text",
                    )}
                </p>
            )}

            {error && (
                <div className="cat-alert cat-alert--error" role="alert">
                    <span>{error.message}</span>
                    {error.code === "batch_size_exceeded" && (
                        <span className="cat-alert__detail">
                            {__("Please select fewer items and try again.", "context-alt-text")}
                        </span>
                    )}
                    <Button variant="default" size="sm" onClick={reset} className="cat-alert__action">
                        {__("Dismiss", "context-alt-text")}
                    </Button>
                </div>
            )}
        </section>
    );
};
