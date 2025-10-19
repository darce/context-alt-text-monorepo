import React from "react";
import { __, _n, sprintf } from "@wordpress/i18n";
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
    onDrilldown?: () => void;
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

export const CoverageCard = ({ data, featureFlags, queryState, onDrilldown }: CoverageCardProps): React.JSX.Element => {
    const percent = clampPercent(data.coverage_percent ?? 0);
    const hasLibrary = (data.total ?? 0) > 0;
    const missingCount = data.missing ?? 0;
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
    const canDrilldown = typeof onDrilldown === "function";
    const showActions = !showSkeleton && canDrilldown;
    const drilldownLabel = featureFlags?.workbenchEnabled
        ? __("Review in Workbench", "context-alt-text")
        : __("View missing media", "context-alt-text");

    const latestPoint = trendPoints.length ? trendPoints[trendPoints.length - 1] : null;
    const previousPoint = trendPoints.length > 1 ? trendPoints[trendPoints.length - 2] : null;
    const delta = latestPoint && previousPoint ? latestPoint.coverage - previousPoint.coverage : null;

    const coverageSummaryText = hasLibrary
        ? sprintf(
              /* translators: 1: coverage percentage, 2: number of images missing alt text */
              _n(
                  "Media library coverage is %1$s percent with %2$s image missing alt text.",
                  "Media library coverage is %1$s percent with %2$s images missing alt text.",
                  missingCount,
                  "context-alt-text",
              ),
              formatPercent(percent),
              missingCount,
          )
        : __("Media library is empty. Upload images to track coverage.", "context-alt-text");

    const deltaText =
        delta === null
            ? __("Trend data is not yet available.", "context-alt-text")
            : delta === 0
              ? __("Coverage is unchanged since the previous scan.", "context-alt-text")
              : delta > 0
                ? sprintf(
                      /* translators: %s: number of points coverage increased */
                      __("Coverage increased by %s points since the previous scan.", "context-alt-text"),
                      formatPercent(Math.abs(delta ?? 0)),
                  )
                : sprintf(
                      /* translators: %s: number of points coverage decreased */
                      __("Coverage decreased by %s points since the previous scan.", "context-alt-text"),
                      formatPercent(Math.abs(delta ?? 0)),
                  );

    const handleRetry = React.useCallback(() => {
        if (refetch) {
            void refetch();
        }
    }, [refetch]);

    const buildAnalyticsPayload = React.useCallback(() => {
        return {
            coverage_percent: percent,
            total: data.total ?? 0,
            with_alt: data.with_alt ?? 0,
            missing: data.missing ?? 0,
        };
    }, [data.missing, data.total, data.with_alt, percent]);

    const handleDrilldown = React.useCallback(() => {
        if (!onDrilldown) {
            return;
        }

        emitDashboardEvent("cat_coverage_drilldown", buildAnalyticsPayload());
        onDrilldown();
    }, [buildAnalyticsPayload, onDrilldown]);

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
            : __("Unknown error", "context-alt-text")
        : null;

    return (
        <Card ref={cardRef} title={__("Coverage Progress", "context-alt-text")} className="cat-card--coverage">
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
                                label={sprintf(
                                    /* translators: %s: coverage percentage */
                                    __("Coverage %s%%", "context-alt-text"),
                                    formatPercent(percent),
                                )}
                            />
                        </div>
                        <dl className="cat-coverage__stats">
                            <div>
                                <dt>{__("Total images", "context-alt-text")}</dt>
                                <dd>{data.total}</dd>
                            </div>
                            <div>
                                <dt>{__("With alt text", "context-alt-text")}</dt>
                                <dd>{data.with_alt}</dd>
                            </div>
                            <div>
                                <dt>{__("Missing alt text", "context-alt-text")}</dt>
                                <dd className={data.missing > 0 ? "cat-text-warning" : ""}>{data.missing}</dd>
                            </div>
                        </dl>
                    </>
                ) : (
                    <p className="cat-coverage__empty" role="status">
                        {__(
                            "No Media Library items yet. Upload images to start tracking coverage.",
                            "context-alt-text",
                        )}
                    </p>
                )}
            </div>

            {showError && (
                <div className="cat-alert cat-alert--error" role="alert">
                    <div>
                        {__("Unable to refresh coverage metrics.", "context-alt-text")}
                        {errorMessage && <span className="cat-alert__detail"> {errorMessage}</span>}
                    </div>
                    {refetch && (
                        <Button type="button" variant="subtle" size="sm" onClick={handleRetry}>
                            {__("Try again", "context-alt-text")}
                        </Button>
                    )}
                </div>
            )}

            {showRefetching && (
                <p className="cat-coverage__refresh" role="status" aria-live="polite">
                    {__("Refreshing latest coverage…", "context-alt-text")}
                </p>
            )}

            {showTrend && (
                <div className="cat-coverage__trend">
                    <small>{__("Trend (beta)", "context-alt-text")}</small>
                    <CoverageTrend points={trendPoints} />
                </div>
            )}

            {showActions && (
                <div className="cat-coverage__actions">
                    <Button type="button" variant="primary" size="sm" onClick={handleDrilldown}>
                        {drilldownLabel}
                    </Button>
                </div>
            )}
        </Card>
    );
};
