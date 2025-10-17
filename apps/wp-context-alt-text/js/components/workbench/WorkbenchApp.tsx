import React from "react";

import { __ } from "@wordpress/i18n";

import { SelectionToolbar } from "@/components/workbench/SelectionToolbar";
import { MediaList } from "@/components/workbench/MediaList";
import { RecognitionActions } from "@/components/workbench/RecognitionActions";
import { useRecognitionJob } from "@/admin/hooks/useRecognitionJob";
import { emitDashboardEvent } from "@/admin/analytics";
import { pushSnackbarNotice } from "@/admin/utils/notices";
import type { WorkbenchMediaItem as WorkbenchMediaItemType } from "@/admin/types";

export type WorkbenchViewMode = "grid" | "list";
export type WorkbenchMediaItem = WorkbenchMediaItemType;

export interface WorkbenchAppProps {
    items?: WorkbenchMediaItem[];
    viewMode?: WorkbenchViewMode;
    onGenerateAltText?: (ids: string[]) => void;
    onRegenerateAltText?: (ids: string[]) => void;
    onMarkReviewed?: (ids: string[]) => void;
}
export const WorkbenchApp = ({
    items = [],
    viewMode = "list",
    onGenerateAltText,
    onRegenerateAltText,
    onMarkReviewed,
}: WorkbenchAppProps): React.JSX.Element => {
    const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
    const selectedList = React.useMemo(() => Array.from(selectedIds), [selectedIds]);

    const recognition = useRecognitionJob();
    const jobDetails = recognition.jobDetails;

    React.useEffect(() => {
        setSelectedIds(new Set());
    }, [items]);

    const requestErrorNoticeRef = React.useRef<string | null>(null);
    const jobErrorNoticeRef = React.useRef<string | null>(null);
    const requestErrorEventRef = React.useRef<string | null>(null);
    const jobErrorEventRef = React.useRef<string | null>(null);
    const completedJobEventRef = React.useRef<string | null>(null);
    const lastAttemptedIdsRef = React.useRef<string[]>([]);

    React.useEffect(() => {
        if (!recognition.error) {
            requestErrorNoticeRef.current = null;
            requestErrorEventRef.current = null;
            return;
        }

        const message = recognition.error.message && recognition.error.message.trim() !== ""
            ? recognition.error.message
            : __("Recognition request failed. Review the log for more details.", "context-alt-text");

        const signature = [
            recognition.error.status ?? "unknown",
            message,
            recognition.error.rejected.join(","),
        ].join("|");

        if (requestErrorNoticeRef.current !== signature) {
            requestErrorNoticeRef.current = signature;
            pushSnackbarNotice("error", message);
        }

        if (requestErrorEventRef.current !== signature) {
            requestErrorEventRef.current = signature;
            emitDashboardEvent("cat_workbench_recognition_failed", {
                stage: "request",
                status: recognition.error.status ?? null,
                message,
                rejected: recognition.error.rejected,
            });
        }
    }, [recognition.error]);

    React.useEffect(() => {
        const status = jobDetails?.status ?? null;

        if (status !== "error") {
            jobErrorNoticeRef.current = null;
            jobErrorEventRef.current = null;
            return;
        }

        const message = jobDetails?.error && jobDetails.error.trim() !== ""
            ? jobDetails.error
            : __("Recognition job failed. Review the log for more details.", "context-alt-text");

        const jobId = jobDetails?.id ?? recognition.lastJob?.jobId ?? null;
        const signature = [jobId ?? "unknown", message].join("|");

        if (jobErrorNoticeRef.current !== signature) {
            jobErrorNoticeRef.current = signature;
            pushSnackbarNotice("error", message);
        }

        if (jobErrorEventRef.current !== signature) {
            jobErrorEventRef.current = signature;
            emitDashboardEvent("cat_workbench_recognition_failed", {
                stage: "job",
                jobId,
                message,
                attachments: jobDetails?.attachments?.map((attachment) => attachment.id) ?? [],
                rejected: jobDetails?.rejected ?? [],
            });
        }
    }, [jobDetails?.status, jobDetails?.error, jobDetails?.id, jobDetails?.attachments, jobDetails?.rejected, recognition.lastJob?.jobId]);

    React.useEffect(() => {
        if (!jobDetails || jobDetails.status !== "complete") {
            return;
        }

        const jobId = jobDetails.id ?? recognition.lastJob?.jobId ?? null;
        const signature = jobId ?? `complete:${jobDetails.completedAt ?? Date.now()}`;

        if (completedJobEventRef.current === signature) {
            return;
        }

        completedJobEventRef.current = signature;

        const observationSummary = jobDetails.observations.reduce(
            (acc, item) => {
                acc.total += item.summary.total;
                acc.matched += item.summary.matched;
                acc.needsReview += item.summary.needsReview;
                return acc;
            },
            { total: 0, matched: 0, needsReview: 0 },
        );

        const durationSeconds = jobDetails.startedAt && jobDetails.completedAt
            ? Math.max(0, jobDetails.completedAt - jobDetails.startedAt)
            : null;

        emitDashboardEvent("cat_workbench_recognition_completed", {
            jobId,
            attachments: jobDetails.attachments.map((attachment) => attachment.id),
            attachmentCount: jobDetails.attachments.length,
            observations: observationSummary.total,
            matched: observationSummary.matched,
            needsReview: observationSummary.needsReview,
            rejected: jobDetails.rejected,
            rejectedCount: jobDetails.rejected.length,
            durationSeconds,
        });
    }, [jobDetails, recognition.lastJob?.jobId]);

    const handleToggleSelection = React.useCallback(
        (id: string) => {
            setSelectedIds((prev) => {
                const next = new Set(prev);
                if (next.has(id)) {
                    next.delete(id);
                } else {
                    next.add(id);
                }
                return next;
            });
        },
        [setSelectedIds],
    );

    const clearSelection = React.useCallback(() => setSelectedIds(new Set()), []);

    const handleGenerateAltText = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onGenerateAltText?.(selectedList);
    }, [onGenerateAltText, selectedList]);

    const handleRegenerateAltText = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onRegenerateAltText?.(selectedList);
    }, [onRegenerateAltText, selectedList]);

    const handleMarkReviewed = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onMarkReviewed?.(selectedList);
    }, [onMarkReviewed, selectedList]);

    const handleTriggerRecognition = React.useCallback(() => {
        if (selectedList.length === 0 || !recognition.canSubmit) {
            return;
        }
        const selectionSnapshot = [...selectedList];
        lastAttemptedIdsRef.current = selectionSnapshot;

        requestErrorEventRef.current = null;
        jobErrorEventRef.current = null;
        completedJobEventRef.current = null;

        emitDashboardEvent("cat_workbench_recognition_triggered", {
            selection: selectionSnapshot,
            count: selectionSnapshot.length,
        });

        void recognition.triggerRecognition(selectionSnapshot).catch(() => {
            // Errors are surfaced via the hook state; no additional handling needed here.
        });
    }, [recognition, selectedList]);

    const handleRetryRecognition = React.useCallback(() => {
        const retryIds = lastAttemptedIdsRef.current;

        if (retryIds.length === 0 || !recognition.canSubmit) {
            return;
        }

        requestErrorEventRef.current = null;
        jobErrorEventRef.current = null;

        emitDashboardEvent("cat_workbench_recognition_triggered", {
            selection: retryIds,
            count: retryIds.length,
            retry: true,
        });

        void recognition.triggerRecognition(retryIds).catch(() => {
            // Errors are surfaced via the hook state; no additional handling needed here.
        });
    }, [recognition]);

    return (
        <div
            className="cat-workbench"
            aria-label={__("Alt-Text Workbench", "context-alt-text")}
        >
            <SelectionToolbar
                selectionCount={selectedIds.size}
                onGenerate={handleGenerateAltText}
                onRegenerate={handleRegenerateAltText}
                onMarkReviewed={handleMarkReviewed}
                onClearSelection={clearSelection}
            />

            <div className="cat-workbench__layout">
                <RecognitionActions
                    selectionCount={selectedIds.size}
                    isEnabled={recognition.canSubmit}
                    isSubmitting={recognition.isSubmitting}
                    isPolling={recognition.isPolling}
                    lastJob={recognition.lastJob}
                    jobDetails={jobDetails}
                    error={recognition.error}
                    onTriggerRecognition={handleTriggerRecognition}
                    onRetryRecognition={handleRetryRecognition}
                    onResetRecognition={recognition.reset}
                />
                <MediaList
                    items={items}
                    selectedIds={selectedIds}
                    onToggleSelect={handleToggleSelection}
                    viewMode={viewMode}
                />
            </div>
        </div>
    );
};
