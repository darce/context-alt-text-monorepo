import React from "react";
import type { QueryStatus } from "@tanstack/react-query";

import type { CoverageCard as CoverageCardData, FeatureFlags } from "@/admin/types";
import { emitDashboardEvent } from "@/admin/analytics";
import { Card } from "@/components/dashboard/Card";
import { CoverageDonut } from "@/components/dashboard/CoverageDonut";
import { CoverageTrend } from "@/components/dashboard/CoverageTrend";
import { Button } from "@/components/ui/button";

interface CoverageCardQueryState {
    status: QueryStatus;
    isLoading: boolean;
    isFetching: boolean;
    isError: boolean;
    error: unknown;
    refetch?: () => Promise<unknown>;
    hasEndpoint: boolean;
}

interface CoverageCardProps {
    data: CoverageCardData;
    featureFlags?: FeatureFlags;
    queryState?: CoverageCardQueryState;
}

const clampPercent = (value: number): number => {
    if (Number.isNaN(value)) {
        return 0;
    }

    return Math.min(100, Math.max(0, value));
};

const formatPercent = (value: number): string => {
    if (Number.isNaN(value)) {
        return "0";
    }

    if (value % 1 === 0) {
        return value.toFixed(0);
    }

    return value.toFixed(1);
};

export const CoverageCard = ({ data, featureFlags, queryState }: CoverageCardProps): React.JSX.Element => {
    const percent = clampPercent(data.coverage_percent ?? 0);
    const hasLibrary = (data.total ?? 0) > 0;
    const trendPoints = data.trend_series ?? [];
    const coverageDescriptionId = React.useId();
    const cardRef = React.useRef<HTMLElement | null>(null);
    const hasEmittedSeen = React.useRef(false);
    const hasLoggedTrend = React.useRef(false);

    const refetch = queryState?.refetch;
    const showSkeleton = Boolean(queryState?.hasEndpoint && queryState?.status === "pending");
    const showError = Boolean(queryState?.isError);
    const showRefetching = Boolean(queryState?.isFetching && !showSkeleton && !showError);
    const showTrend = Boolean(featureFlags?.coverageTrend && hasLibrary && trendPoints.length > 1);

    const latestPoint = trendPoints.length ? trendPoints[trendPoints.length - 1] : null;
    const previousPoint = trendPoints.length > 1 ? trendPoints[trendPoints.length - 2] : null;
    const delta = latestPoint && previousPoint ? latestPoint.coverage - previousPoint.coverage : null;

    const coverageSummaryText = hasLibrary
        ? `Media library coverage is ${formatPercent(percent)} percent with ${data.missing} images missing alt text.`
        : "Media library is empty. Upload images to track coverage.";

    const deltaText = delta === null
        ? "Trend data is not yet available."
        : delta === 0
          ? "Coverage is unchanged since the previous scan."
          : `Coverage ${delta > 0 ? "increased" : "decreased"} by ${formatPercent(Math.abs(delta))} points since the previous scan.`;

    const handleRetry = React.useCallback(() => {
        if (refetch) {
            void refetch();
        }
    }, [refetch]);

    React.useEffect(() => {
        if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") {
            return;
        }

        if (!cardRef.current || hasEmittedSeen.current) {
            return;
        }

        const observer = new IntersectionObserver(
            (entries) => {
                const isVisible = entries.some((entry) => entry.isIntersecting);

                if (isVisible) {
                    hasEmittedSeen.current = true;
                    emitDashboardEvent("cat_dashboard_card_seen", {
                        card: "coverage",
                        coverage_percent: percent,
                    });
                    observer.disconnect();
                }
            },
            { threshold: 0.4 },
        );

        observer.observe(cardRef.current);

        return () => {
            observer.disconnect();
        };
    }, [percent]);

    React.useEffect(() => {
        if (!showTrend || hasLoggedTrend.current) {
            return;
        }

        hasLoggedTrend.current = true;
        emitDashboardEvent("cat_dashboard_coverage_trend_enabled", {
            card: "coverage",
            trend_points: trendPoints.length,
        });
    }, [showTrend, trendPoints.length]);

    const errorMessage = showError
        ? queryState?.error instanceof Error
            ? queryState.error.message
            : "Unknown error"
        : null;

    return (
        <Card ref={cardRef} title="Coverage Progress" className="cat-card--coverage">
            <div className="cat-coverage">
                <span id={coverageDescriptionId} className="cat-sr-only">
                    {coverageSummaryText} {deltaText}
                </span>

                {showSkeleton ? (
                    <div className="cat-coverage__skeleton" role="status" aria-live="polite">
                        <div className="cat-skeleton cat-skeleton--donut" />
                        <div className="cat-skeleton cat-skeleton--line" />
                        <div className="cat-skeleton cat-skeleton--line" />
                        <div className="cat-skeleton cat-skeleton--line" />
                    </div>
                ) : hasLibrary ? (
                    <>
                        <div className="cat-coverage__metric">
                            <span className="cat-coverage__metric-value">{formatPercent(percent)}%</span>
                            <CoverageDonut
                                value={percent}
                                describedBy={coverageDescriptionId}
                                label={`Coverage ${formatPercent(percent)}%`}
                            />
                        </div>
                        <dl className="cat-coverage__stats">
                            <div>
                                <dt>Total images</dt>
                                <dd>{data.total}</dd>
                            </div>
                            <div>
                                <dt>With alt text</dt>
                                <dd>{data.with_alt}</dd>
                            </div>
                            <div>
                                <dt>Missing alt text</dt>
                                <dd className={data.missing > 0 ? "cat-text-warning" : ""}>{data.missing}</dd>
                            </div>
                        </dl>
                    </>
                ) : (
                    <p className="cat-coverage__empty" role="status">
                        No Media Library items yet. Upload images to start tracking coverage.
                    </p>
                )}
            </div>

            {showError && (
                <div className="cat-alert cat-alert--error" role="alert">
                    <div>
                        Unable to refresh coverage metrics.
                        {errorMessage && <span className="cat-alert__detail"> {errorMessage}</span>}
                    </div>
                    {refetch && (
                        <Button
                            type="button"
                            variant="subtle"
                            size="sm"
                            onClick={handleRetry}
                        >
                            Try again
                        </Button>
                    )}
                </div>
            )}

            {showRefetching && (
                <p className="cat-coverage__refresh" role="status" aria-live="polite">
                    Refreshing latest coverage…
                </p>
            )}

            {showTrend && (
                <div className="cat-coverage__trend">
                    <small>Trend (beta)</small>
                    <CoverageTrend points={trendPoints} />
                </div>
            )}
        </Card>
    );
};
