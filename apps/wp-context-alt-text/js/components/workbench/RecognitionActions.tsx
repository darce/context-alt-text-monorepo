import React from "react";

import { __, _n, sprintf } from "@wordpress/i18n";
import { Link } from "react-router-dom";

import type {
    RecognitionAttachmentObservations,
    RecognitionJobDetails,
    RecognitionJobSummary,
    RecognitionRequestError,
} from "@/admin/hooks/useRecognitionJob";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { getDashboardConfig } from "@/admin/dashboardData";

export interface RecognitionActionsProps {
    selectionCount: number;
    isEnabled: boolean;
    isSubmitting: boolean;
    isPolling: boolean;
    lastJob?: RecognitionJobSummary | null;
    jobDetails?: RecognitionJobDetails | null;
    error?: RecognitionRequestError | null;
    onTriggerRecognition?: () => void;
    onRetryRecognition?: () => void;
    onResetRecognition?: () => void;
}

export const RecognitionActions = ({
    selectionCount,
    isEnabled,
    isSubmitting,
    isPolling,
    lastJob = null,
    jobDetails = null,
    error = null,
    onTriggerRecognition,
    onRetryRecognition,
    onResetRecognition,
}: RecognitionActionsProps): React.JSX.Element => {
    const config = React.useMemo(() => getDashboardConfig(), []);
    const rosterEnabled = Boolean(config.featureFlags?.rosterEnabled);
    const buttonDisabled = !isEnabled || selectionCount === 0 || isSubmitting;
    const [shouldRenderProgress, setShouldRenderProgress] = React.useState(false);

    const aggregateSummary = React.useMemo(() => {
        if (!jobDetails || jobDetails.observations.length === 0) {
            return null;
        }

        return jobDetails.observations.reduce(
            (acc, item) => {
                acc.total += item.summary.total;
                acc.matched += item.summary.matched;
                acc.needsReview += item.summary.needsReview;
                return acc;
            },
            { total: 0, matched: 0, needsReview: 0 },
        );
    }, [jobDetails]);

    const selectionSummary = React.useMemo(() => {
        const rejectedCount = lastJob?.rejected.length ?? 0;

        return {
            selected: selectionCount,
            accepted: lastJob?.accepted ?? 0,
            rejected: rejectedCount,
            matched: aggregateSummary?.matched ?? 0,
            totalObservations: aggregateSummary?.total ?? 0,
            needsReview: aggregateSummary?.needsReview ?? 0,
        };
    }, [selectionCount, lastJob, aggregateSummary]);

    const jobStatus = jobDetails?.status ?? lastJob?.status ?? null;
    const progressPhase = React.useMemo(() => {
        if (isSubmitting) {
            return "submitting" as const;
        }

        if (isPolling || jobStatus === "processing") {
            return "processing" as const;
        }

        if (shouldRenderProgress) {
            return "pending" as const;
        }

        return "idle" as const;
    }, [isSubmitting, isPolling, jobStatus, shouldRenderProgress]);

    const progressLabel = React.useMemo(() => {
        switch (progressPhase) {
            case "submitting":
                return __("Submitting recognition job…", "context-alt-text");
            case "processing":
                return __("Recognition job is running. Results will update automatically.", "context-alt-text");
            case "pending":
                return __("Preparing recognition job…", "context-alt-text");
            default:
                return null;
        }
    }, [progressPhase]);

    const progressValue = React.useMemo(() => {
        switch (progressPhase) {
            case "submitting":
                return 15;
            case "processing":
                return jobStatus === "complete" ? 100 : 65;
            case "pending":
                return 5;
            default:
                return 0;
        }
    }, [progressPhase, jobStatus]);

    const showProgress = shouldRenderProgress && progressPhase !== "idle" && progressLabel !== null;

    React.useEffect(() => {
        if (isSubmitting || isPolling || jobStatus === "processing") {
            if (!shouldRenderProgress) {
                setShouldRenderProgress(true);
            }
            return;
        }

        if (shouldRenderProgress && !isSubmitting && !isPolling) {
            if (jobStatus === "complete" || jobStatus === "error" || error) {
                setShouldRenderProgress(false);
            }
        }
    }, [isSubmitting, isPolling, jobStatus, error, shouldRenderProgress]);

    const handleTriggerClick = React.useCallback(() => {
        if (buttonDisabled) {
            return;
        }

        setShouldRenderProgress(true);
        onTriggerRecognition?.();
    }, [buttonDisabled, onTriggerRecognition]);

    const jobMessage = React.useMemo(() => {
        if (!lastJob) {
            return null;
        }

        const { accepted, rejected, jobId, status } = lastJob;
        const effectiveStatus = jobDetails?.status ?? status;
        const acceptedCopy = sprintf(
            _n("Queued %d item for recognition.", "Queued %d items for recognition.", accepted, "context-alt-text"),
            accepted,
        );

        const jobIdCopy = jobId
            ? sprintf(
                  // translators: %s is the recognition job identifier.
                  __("Job ID: %s.", "context-alt-text"),
                  jobId,
              )
            : null;

        const rejectedCount = rejected.length;
        const rejectedCopy = rejectedCount
            ? sprintf(
                  _n(
                      "Skipped %d unsupported item.",
                      "Skipped %d unsupported items.",
                      rejectedCount,
                      "context-alt-text",
                  ),
                  rejectedCount,
              )
            : null;

        let statusCopy: string;

        if (effectiveStatus === "complete") {
            if (aggregateSummary) {
                statusCopy = sprintf(
                    // translators: 1: matched observation count, 2: total observation count.
                    __("Recognition job completed. Matched %1$d of %2$d observations.", "context-alt-text"),
                    aggregateSummary.matched,
                    aggregateSummary.total,
                );
            } else {
                statusCopy = __("Recognition job completed.", "context-alt-text");
            }
        } else if (effectiveStatus === "error") {
            statusCopy = __("Recognition job failed. Review the log for more details.", "context-alt-text");
        } else if (isPolling) {
            statusCopy = __("Recognition job is running. Results will update automatically.", "context-alt-text");
        } else {
            statusCopy = __(
                "Recognition job queued. Results will appear once processing finishes.",
                "context-alt-text",
            );
        }

        return [acceptedCopy, jobIdCopy, rejectedCopy, statusCopy].filter(Boolean).join(" ");
    }, [lastJob, jobDetails, aggregateSummary, isPolling]);

    const errorMessage = error?.message ?? null;
    const errorRejectedMessage = React.useMemo(() => {
        if (!error || error.rejected.length === 0) {
            return null;
        }

        const rejectedList = error.rejected.map((value) => String(value)).join(", ");

        return sprintf(
            // translators: %s is a comma-separated list of attachment IDs.
            __("Skipped attachments: %s.", "context-alt-text"),
            rejectedList,
        );
    }, [error]);

    const handleRetryClick = React.useCallback(() => {
        if (onResetRecognition) {
            onResetRecognition();
        }
        if (onRetryRecognition) {
            onRetryRecognition();
        }
    }, [onResetRecognition, onRetryRecognition]);

    const showRetryButton = Boolean(error && onRetryRecognition && !isSubmitting);

    return (
        <section className="cat-workbench__panel" aria-label={__("Recognition actions", "context-alt-text")}>
            <header>
                <h2>{__("Recognition", "context-alt-text")}</h2>
                <p>{__("Run face and brand detection to enrich context for selected items.", "context-alt-text")}</p>
            </header>
            <Button variant="default" size="md" onClick={handleTriggerClick} disabled={buttonDisabled}>
                {isSubmitting ? __("Triggering…", "context-alt-text") : __("Trigger Recognition", "context-alt-text")}
            </Button>

            <dl className="cat-recognition__summary" aria-live="polite">
                <div>
                    <dt>{__("Selected items", "context-alt-text")}</dt>
                    <dd>{selectionSummary.selected}</dd>
                </div>
                <div>
                    <dt>{__("Queued", "context-alt-text")}</dt>
                    <dd>{selectionSummary.accepted}</dd>
                </div>
                <div>
                    <dt>{__("Skipped", "context-alt-text")}</dt>
                    <dd>{selectionSummary.rejected}</dd>
                </div>
                {aggregateSummary && (
                    <>
                        <div>
                            <dt>{__("Matched", "context-alt-text")}</dt>
                            <dd>{selectionSummary.matched}</dd>
                        </div>
                        <div>
                            <dt>{__("Needs review", "context-alt-text")}</dt>
                            <dd>{selectionSummary.needsReview}</dd>
                        </div>
                        <div>
                            <dt>{__("Observations", "context-alt-text")}</dt>
                            <dd>{selectionSummary.totalObservations}</dd>
                        </div>
                    </>
                )}
            </dl>

            {!isEnabled && (
                <small className="cat-recognition__hint">
                    {__("Enable recognition from the plugin settings to activate this action.", "context-alt-text")}
                </small>
            )}

            {showProgress && progressLabel && (
                <div className="cat-recognition__progress" role="status" aria-live="polite">
                    <p>{progressLabel}</p>
                    <Progress value={progressValue} aria-label={progressLabel} />
                </div>
            )}

            {!isSubmitting && jobMessage && (
                <p
                    className="cat-recognition__status cat-recognition__status--success"
                    role="status"
                    aria-live="polite"
                >
                    {jobMessage}
                </p>
            )}

            {errorMessage && (
                <div className="cat-alert cat-alert--error" role="alert">
                    <span>{errorMessage}</span>
                    {errorRejectedMessage && <span className="cat-alert__detail">{errorRejectedMessage}</span>}
                    {showRetryButton && (
                        <Button variant="default" size="sm" onClick={handleRetryClick} className="cat-alert__action">
                            {__("Retry", "context-alt-text")}
                        </Button>
                    )}
                </div>
            )}

            {jobDetails && jobDetails.observations.length > 0 && (
                <section aria-label={__("Recognition results", "context-alt-text")}>
                    <h3 className="cat-recognition__results-title">{__("Recognition results", "context-alt-text")}</h3>
                    <ul className="cat-recognition__results">
                        {jobDetails.observations.map((item) => (
                            <RecognitionResultRow
                                key={item.attachmentId}
                                observation={item}
                                rosterEnabled={rosterEnabled}
                            />
                        ))}
                    </ul>
                </section>
            )}
        </section>
    );
};

const RecognitionResultRow = ({
    observation,
    rosterEnabled,
}: {
    observation: RecognitionAttachmentObservations;
    rosterEnabled: boolean;
}): React.JSX.Element => {
    const summary = observation.summary;
    const unresolved = Math.max(summary.needsReview, summary.total - summary.matched);
    const hasObservations = observation.observations.length > 0;

    const matchedObservations = React.useMemo(
        () => observation.observations.filter((record) => record.status === "matched"),
        [observation.observations],
    );

    const needsReviewObservations = React.useMemo(
        () => observation.observations.filter((record) => record.status === "needs_review"),
        [observation.observations],
    );

    return (
        <li className="cat-recognition__result" data-attachment-id={observation.attachmentId}>
            <div className="cat-recognition__result-header">
                <strong>
                    {observation.context.filename ??
                        sprintf(
                            // translators: %d is an attachment identifier.
                            __("Attachment %d", "context-alt-text"),
                            observation.attachmentId,
                        )}
                </strong>
                {observation.context.imageUrl && (
                    <a
                        href={observation.context.imageUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="cat-recognition__result-link"
                    >
                        {__("Open", "context-alt-text")}
                    </a>
                )}
            </div>
            <dl className="cat-recognition__result-stats">
                <div>
                    <dt>{__("Total", "context-alt-text")}</dt>
                    <dd>{summary.total}</dd>
                </div>
                <div>
                    <dt>{__("Matched", "context-alt-text")}</dt>
                    <dd>{summary.matched}</dd>
                </div>
                <div>
                    <dt>{__("Needs review", "context-alt-text")}</dt>
                    <dd>{unresolved}</dd>
                </div>
            </dl>
            {hasObservations && (
                <div className="cat-recognition__observation-groups">
                    {matchedObservations.length > 0 && (
                        <section
                            className="cat-recognition__observation-section"
                            aria-label={__("Matched observations", "context-alt-text")}
                        >
                            <h4 className="cat-recognition__observation-section-title">
                                {__("Matched", "context-alt-text")}
                            </h4>
                            <ul className="cat-recognition__observation-list">
                                {matchedObservations.map((record) => (
                                    <RecognitionObservationRow
                                        key={record.observationId}
                                        record={record}
                                        rosterEnabled={rosterEnabled}
                                        attachmentId={observation.attachmentId}
                                    />
                                ))}
                            </ul>
                        </section>
                    )}
                    {needsReviewObservations.length > 0 && (
                        <section
                            className="cat-recognition__observation-section"
                            aria-label={__("Observations needing review", "context-alt-text")}
                        >
                            <h4 className="cat-recognition__observation-section-title">
                                {__("Needs Review", "context-alt-text")}
                            </h4>
                            <ul className="cat-recognition__observation-list">
                                {needsReviewObservations.map((record) => (
                                    <RecognitionObservationRow
                                        key={record.observationId}
                                        record={record}
                                        rosterEnabled={rosterEnabled}
                                        attachmentId={observation.attachmentId}
                                    />
                                ))}
                            </ul>
                        </section>
                    )}
                </div>
            )}
        </li>
    );
};

interface RecognitionObservationRowProps {
    record: RecognitionAttachmentObservations["observations"][number];
    rosterEnabled: boolean;
    attachmentId: RecognitionAttachmentObservations["attachmentId"];
}

const formatStatusLabel = (status: string): string => {
    switch (status) {
        case "matched":
            return __("Matched", "context-alt-text");
        case "needs_review":
            return __("Needs review", "context-alt-text");
        default:
            return status.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
    }
};

const RecognitionObservationRow = ({
    record,
    rosterEnabled,
    attachmentId,
}: RecognitionObservationRowProps): React.JSX.Element => {
    const rosterMatch = record.roster;
    const hasRosterMatch = Boolean(rosterMatch?.remoteId);
    const needsReview = record.status === "needs_review";

    const rosterSearch = new URLSearchParams();
    if (hasRosterMatch && rosterMatch?.remoteId) {
        rosterSearch.set("remoteId", rosterMatch.remoteId);
    } else {
        rosterSearch.set("mode", "create");
        if (record.label) {
            rosterSearch.set("label", record.label);
        }
    }

    if (record.observationId) {
        rosterSearch.set("observationId", record.observationId);
    }

    if (attachmentId) {
        rosterSearch.set("attachmentId", String(attachmentId));
    }

    rosterSearch.set("source", "recognition");

    const rosterLink = `/roster?${rosterSearch.toString()}`;

    const defaultRosterCta = hasRosterMatch
        ? __("Open roster entry", "context-alt-text")
        : __("Add to roster", "context-alt-text");
    const reviewRosterCta = hasRosterMatch
        ? __("Review roster entry", "context-alt-text")
        : __("Review in roster manager", "context-alt-text");

    const displayLabel = record.label ?? record.entityType ?? __("Observation", "context-alt-text");

    const rosterDescription = rosterMatch
        ? sprintf(
              /* translators: %s is a roster display name. */
              __("Linked to roster entry %s", "context-alt-text"),
              rosterMatch.displayName ??
                  rosterMatch.name ??
                  rosterMatch.remoteId ??
                  __("(unknown)", "context-alt-text"),
          )
        : __("No roster match", "context-alt-text");

    let action: React.ReactNode = null;

    if (needsReview) {
        if (rosterEnabled) {
            action = (
                <Button asChild variant="primary" size="sm">
                    <Link to={rosterLink} aria-label={`${reviewRosterCta}: ${displayLabel}`}>
                        {reviewRosterCta}
                    </Link>
                </Button>
            );
        } else {
            action = (
                <span className="cat-recognition__observation-helper">
                    {__("Enable the roster manager from settings to resolve this observation.", "context-alt-text")}
                </span>
            );
        }
    } else if (rosterEnabled && hasRosterMatch) {
        action = (
            <Link
                to={rosterLink}
                className="cat-recognition__observation-link"
                aria-label={`${defaultRosterCta}: ${displayLabel}`}
            >
                {defaultRosterCta}
            </Link>
        );
    } else if (rosterEnabled && record.status !== "matched") {
        action = (
            <Link
                to={rosterLink}
                className="cat-recognition__observation-link"
                aria-label={`${defaultRosterCta}: ${displayLabel}`}
            >
                {defaultRosterCta}
            </Link>
        );
    }

    return (
        <li className="cat-recognition__observation">
            <div className="cat-recognition__observation-header">
                <span className="cat-recognition__observation-label">{displayLabel}</span>
                <span
                    className={`cat-recognition__observation-status cat-recognition__observation-status--${record.status}`}
                >
                    {formatStatusLabel(record.status)}
                </span>
            </div>
            <div className="cat-recognition__observation-body">
                <span className="cat-recognition__observation-meta">{rosterDescription}</span>
                {action}
            </div>
        </li>
    );
};
