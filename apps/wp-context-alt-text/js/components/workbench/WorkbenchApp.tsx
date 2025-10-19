import React from "react";

import { __ } from "@wordpress/i18n";

import { SelectionToolbar } from "@/components/workbench/SelectionToolbar";
import { MediaList } from "@/components/workbench/MediaList";
import { RecognitionActions } from "@/components/workbench/RecognitionActions";
import { useRecognitionJob } from "@/admin/hooks/useRecognitionJob";
import { useWorkbenchActions } from "@/components/workbench/useWorkbenchActions";
import { emitDashboardEvent } from "@/admin/analytics";
import { dispatchNotice } from "@/admin/notices";
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

    /**
     * Combined error handling effect for both request and job errors
     * Handles error notifications and analytics tracking with deduplication
     */
    React.useEffect(() => {
        // Handle request errors
        if (recognition.error) {
            const message =
                recognition.error.message && recognition.error.message.trim() !== ""
                    ? recognition.error.message
                    : __("Recognition request failed. Review the log for more details.", "context-alt-text");

            const signature = [
                recognition.error.status ?? "unknown",
                message,
                recognition.error.rejected.join(","),
            ].join("|");

            if (requestErrorNoticeRef.current !== signature) {
                requestErrorNoticeRef.current = signature;
                dispatchNotice("error", message, { id: "cat-workbench-error" });
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
        } else {
            requestErrorNoticeRef.current = null;
            requestErrorEventRef.current = null;
        }

        // Handle job errors
        const status = jobDetails?.status ?? null;

        if (status === "error") {
            const message =
                jobDetails?.error && jobDetails.error.trim() !== ""
                    ? jobDetails.error
                    : __("Recognition job failed. Review the log for more details.", "context-alt-text");

            const jobId = jobDetails?.id ?? recognition.lastJob?.jobId ?? null;
            const signature = [jobId ?? "unknown", message].join("|");

            if (jobErrorNoticeRef.current !== signature) {
                jobErrorNoticeRef.current = signature;
                dispatchNotice("error", message, { id: "cat-workbench-job-error" });
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
        } else {
            jobErrorNoticeRef.current = null;
            jobErrorEventRef.current = null;
        }
    }, [
        recognition.error,
        jobDetails?.status,
        jobDetails?.error,
        jobDetails?.id,
        jobDetails?.attachments,
        jobDetails?.rejected,
        recognition.lastJob?.jobId,
    ]);

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

        const durationSeconds =
            jobDetails.startedAt && jobDetails.completedAt
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

    // Extract all action handlers to custom hook
    const actions = useWorkbenchActions({
        selectedList,
        setSelectedIds,
        recognition,
        lastAttemptedIdsRef,
        requestErrorEventRef,
        jobErrorEventRef,
        completedJobEventRef,
        onGenerateAltText,
        onRegenerateAltText,
        onMarkReviewed,
    });

    return (
        <div className="cat-workbench" aria-label={__("Alt-Text Workbench", "context-alt-text")}>
            <SelectionToolbar
                selectionCount={selectedIds.size}
                onGenerate={actions.handleGenerateAltText}
                onRegenerate={actions.handleRegenerateAltText}
                onMarkReviewed={actions.handleMarkReviewed}
                onClearSelection={actions.clearSelection}
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
                    onTriggerRecognition={actions.handleTriggerRecognition}
                    onRetryRecognition={actions.handleRetryRecognition}
                    onResetRecognition={recognition.reset}
                />
                <MediaList
                    items={items}
                    selectedIds={selectedIds}
                    onToggleSelect={actions.handleToggleSelection}
                    viewMode={viewMode}
                />
            </div>
        </div>
    );
};
