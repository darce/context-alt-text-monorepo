import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { renderDashboard } from "@/admin/testing/renderDashboard";
import { useDashboardHandlers } from "@/admin/testing/mswServer";
import { setAdminBootstrap } from "@/admin/globals";
import type { AnalyticsClient, GlobalPayload } from "@/admin/types";
import { WorkbenchApp, type WorkbenchMediaItem } from "@/components/workbench";

type AdminPayload = GlobalPayload & {
    config: {
        restNonce?: string;
        endpoints?: {
            recognitionAnalyze?: string;
            recognitionJob?: string;
        };
        featureFlags?: {
            workbenchEnabled?: boolean;
            workbenchRecognition?: boolean;
            abilitiesEnabled?: boolean;
            rosterEnabled?: boolean;
        };
    };
    data: {
        workbench: {
            items: WorkbenchMediaItem[];
            viewMode: "list" | "grid";
            pagination: {
                page: number;
                perPage: number;
                total: number;
                totalPages: number;
            };
        };
    };
    analytics?: AnalyticsClient;
};

const baseItem: WorkbenchMediaItem = {
    id: "101",
    title: "Sample asset",
    status: "missing",
    thumbnailUrl: undefined,
    updatedAt: undefined,
    altText: null,
    mimeType: "image/jpeg",
    dimensions: { width: 800, height: 600 },
    editUrl: "http://example.test/wp-admin/post.php?post=101&action=edit",
};

let trackSpy: ReturnType<typeof vi.fn>;

const setAdminPayload = (overrides: Partial<AdminPayload> = {}) => {
    const base: AdminPayload = {
        config: {
            restNonce: "nonce-test",
            endpoints: {
                recognitionAnalyze: "/wp-json/context-alt-text/v1/recognition/analyze",
                recognitionJob: "/wp-json/context-alt-text/v1/recognition/job/",
            },
            featureFlags: {
                workbenchEnabled: true,
                workbenchRecognition: true,
                abilitiesEnabled: true,
                rosterEnabled: true,
            },
        },
        data: {
            workbench: {
                items: [],
                viewMode: "list",
                pagination: {
                    page: 1,
                    perPage: 20,
                    total: 1,
                    totalPages: 1,
                },
            },
        },
        analytics: { track: trackSpy },
    };

    const payload: AdminPayload = {
        config: {
            ...base.config,
            ...overrides.config,
            endpoints: {
                ...base.config.endpoints,
                ...overrides.config?.endpoints,
            },
            featureFlags: {
                ...base.config.featureFlags,
                ...overrides.config?.featureFlags,
            },
        },
        data: {
            ...base.data,
            ...overrides.data,
            workbench: {
                ...base.data.workbench,
                ...overrides.data?.workbench,
                items: overrides.data?.workbench?.items ?? base.data.workbench.items,
                pagination: {
                    ...base.data.workbench.pagination,
                    ...overrides.data?.workbench?.pagination,
                },
            },
        },
        analytics: overrides.analytics ?? base.analytics,
    };

    setAdminBootstrap(payload);
};

describe("RecognitionActions integration", () => {
    let createNotice: ReturnType<typeof vi.fn>;
    let removeNotice: ReturnType<typeof vi.fn>;
    let dispatchMock: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        trackSpy = vi.fn();
        createNotice = vi.fn();
        removeNotice = vi.fn();
        dispatchMock = vi.fn().mockReturnValue({ createNotice, removeNotice });

        (globalThis as typeof globalThis & { wp?: unknown }).wp = {
            data: {
                dispatch: dispatchMock,
            },
        };

        setAdminPayload();
    });

    afterEach(() => {
        setAdminBootstrap(undefined);
        delete (globalThis as typeof globalThis & { wp?: unknown }).wp;
        vi.restoreAllMocks();
    });

    it("disables recognition trigger when feature flag is off", async () => {
        setAdminPayload({
            config: {
                featureFlags: {
                    workbenchRecognition: false,
                },
            },
        });

        const { user } = renderDashboard(
            <WorkbenchApp
                items={[baseItem]}
                viewMode="list"
            />,
            { withRouter: true },
        );

        await user.click(screen.getByLabelText(/select sample asset/i));

        const triggerButton = screen.getByRole("button", { name: /trigger recognition/i });
        expect(triggerButton).toBeDisabled();
        expect(screen.getByText(/enable recognition from the plugin settings/i)).toBeInTheDocument();
        expect(createNotice).not.toHaveBeenCalled();
        expect(trackSpy).not.toHaveBeenCalled();
    });

    it("submits recognition request and surfaces success state", async () => {
        const requestBodies: Record<string, unknown>[] = [];

        useDashboardHandlers(
            http.post("/wp-json/context-alt-text/v1/recognition/analyze", async ({ request }) => {
                const body = (await request.json()) as Record<string, unknown>;
                requestBodies.push(body);

                return HttpResponse.json({
                    jobId: "job-abc",
                    status: "processing",
                    accepted: 1,
                    rejected: [],
                });
            }),
            http.get("/wp-json/context-alt-text/v1/recognition/job/:jobId", ({ params }) => {
                if (params.jobId !== "job-abc") {
                    return HttpResponse.json({ message: "Not found" }, { status: 404 });
                }

                return HttpResponse.json({
                    id: "job-abc",
                    status: "complete",
                    attachments: [
                        {
                            id: 101,
                            filename: "sample.png",
                            imageUrl: "http://example.test/uploads/sample.png",
                        },
                    ],
                    rejected: [],
                    startedAt: 10,
                    completedAt: 15,
                    observations: [
                        {
                            jobId: "job-abc",
                            attachmentId: 101,
                            updatedAt: 1_700_000_000,
                            context: {
                                filename: "sample.png",
                                imageUrl: "http://example.test/uploads/sample.png",
                            },
                            summary: {
                                total: 2,
                                matched: 1,
                                needs_review: 1,
                            },
                            observations: [
                                {
                                    observationId: "job-abc-0",
                                    label: "Face",
                                    entityType: "person",
                                    confidence: 0.95,
                                    area: 120.5,
                                    boundingBox: [0, 0, 10, 10],
                                    status: "matched",
                                    source: "recognition-service",
                                    match: {
                                        is_match: true,
                                        similarity_score: 0.92,
                                        match_confidence: 92,
                                        confidence_threshold: 0.5,
                                    },
                                    roster: {
                                        unique_id: "roster-123",
                                        name: "Test User",
                                        display_name: "Test User",
                                    },
                                    candidates: [],
                                },
                                {
                                    observationId: "job-abc-1",
                                    label: "Face",
                                    entityType: "person",
                                    confidence: 0.45,
                                    area: 80,
                                    boundingBox: [1, 2, 3, 4],
                                    status: "needs_review",
                                    source: "recognition-service",
                                    match: {
                                        is_match: false,
                                        similarity_score: 0.4,
                                        match_confidence: 40,
                                        confidence_threshold: 0.5,
                                    },
                                    roster: null,
                                    candidates: [],
                                },
                            ],
                        },
                    ],
                });
            }),
        );

        const { user } = renderDashboard(
            <WorkbenchApp
                items={[baseItem]}
                viewMode="list"
            />,
            { withRouter: true },
        );

        await user.click(screen.getByLabelText(/select sample asset/i));
        await user.click(screen.getByRole("button", { name: /trigger recognition/i }));

        expect(trackSpy).toHaveBeenCalledWith(
            "cat_workbench_recognition_triggered",
            expect.objectContaining({ count: 1, selection: ["101"] }),
        );

        await waitFor(() => {
            expect(requestBodies).toHaveLength(1);
        });
        expect(requestBodies[0]).toMatchObject({ attachment_ids: [101] });

        expect(await screen.findByText(/recognition job completed/i)).toBeInTheDocument();
        expect(screen.getByText(/job id: job-abc/i)).toBeInTheDocument();

        const rosterLink = await screen.findByRole("link", { name: /open roster entry/i });
        expect(rosterLink).toHaveAttribute("href", expect.stringContaining("remoteId=roster-123"));

        const reviewLink = screen.getByRole("link", { name: /review in roster manager/i });
        expect(reviewLink).toHaveAttribute("href", expect.stringContaining("mode=create"));
        expect(reviewLink).toHaveAttribute("href", expect.stringContaining("source=recognition"));
        expect(reviewLink).toHaveAttribute("href", expect.stringContaining("observationId=job-abc-1"));
        expect(reviewLink).toHaveAttribute("href", expect.stringContaining("attachmentId=101"));

        const needsReviewMetrics = screen.getAllByText(/needs review/i, { selector: "dt" });
        expect(needsReviewMetrics).toHaveLength(2);

        const [firstNeedsReview, secondNeedsReview] = needsReviewMetrics;
        expect(firstNeedsReview).toBeDefined();
        expect(secondNeedsReview).toBeDefined();

        expect(firstNeedsReview!.closest("div")?.querySelector("dd")).toHaveTextContent("1");
        expect(secondNeedsReview!.closest("div")?.querySelector("dd")).toHaveTextContent("1");

        const selectedMetric = screen.getAllByText(/selected items/i, { selector: "dt" })[0]?.closest("div");
        expect(selectedMetric?.querySelector("dd")).toHaveTextContent("1");

        await waitFor(() => {
            expect(trackSpy).toHaveBeenCalledWith(
                "cat_workbench_recognition_completed",
                expect.objectContaining({
                    jobId: "job-abc",
                    attachmentCount: 1,
                    observations: 2,
                    matched: 1,
                    needsReview: 1,
                    durationSeconds: 5,
                }),
            );
        });

        expect(createNotice).not.toHaveBeenCalled();
    });

    it("submits only the explicitly selected media items when multiple rows are present", async () => {
        const requestBodies: Record<string, unknown>[] = [];

        useDashboardHandlers(
            http.post("/wp-json/context-alt-text/v1/recognition/analyze", async ({ request }) => {
                const body = (await request.json()) as Record<string, unknown>;
                requestBodies.push(body);

                return HttpResponse.json({
                    jobId: "job-multi",
                    status: "processing",
                    accepted: 1,
                    rejected: [],
                });
            }),
            http.get("/wp-json/context-alt-text/v1/recognition/job/:jobId", ({ params }) => {
                if (params.jobId !== "job-multi") {
                    return HttpResponse.json({ message: "not-found" }, { status: 404 });
                }

                return HttpResponse.json({
                    id: "job-multi",
                    status: "complete",
                    attachments: [],
                    rejected: [],
                    observations: [],
                });
            }),
        );

        const extraItems: WorkbenchMediaItem[] = [
            baseItem,
            {
                ...baseItem,
                id: "202",
                title: "Second asset",
            },
            {
                ...baseItem,
                id: "303",
                title: "Third asset",
            },
        ];

        const { user } = renderDashboard(
            <WorkbenchApp
                items={extraItems}
                viewMode="list"
            />,
            { withRouter: true },
        );

        await user.click(screen.getByLabelText(/select second asset/i));
        await user.click(screen.getByRole("button", { name: /trigger recognition/i }));

        await waitFor(() => {
            expect(requestBodies).toHaveLength(1);
        });

        expect(requestBodies[0]).toMatchObject({ attachment_ids: [202] });
    });

    it("surfaces error details when recognition fails", async () => {
        useDashboardHandlers(
            http.post("/wp-json/context-alt-text/v1/recognition/analyze", () => {
                return HttpResponse.json(
                    {
                        code: "cat_recognition_no_valid_attachments",
                        message: "No valid attachments were provided.",
                        data: {
                            status: 400,
                            rejected: [555],
                        },
                    },
                    { status: 400 },
                );
            }),
        );

        const { user } = renderDashboard(
            <WorkbenchApp
                items={[baseItem]}
                viewMode="list"
            />,
            { withRouter: true },
        );

        await user.click(screen.getByLabelText(/select sample asset/i));
        await user.click(screen.getByRole("button", { name: /trigger recognition/i }));

        expect(trackSpy).toHaveBeenCalledWith(
            "cat_workbench_recognition_triggered",
            expect.objectContaining({ count: 1 }),
        );

        const alert = await screen.findByRole("alert");
        expect(alert).toHaveTextContent(/no valid attachments were provided/i);
        expect(alert).toHaveTextContent(/555/);

        await waitFor(() => {
            expect(createNotice).toHaveBeenCalledWith(
                "error",
                "No valid attachments were provided.",
                expect.objectContaining({ id: "cat-recognition-job-error" }),
            );
        });

        await waitFor(() => {
            expect(trackSpy).toHaveBeenCalledWith(
                "cat_workbench_recognition_failed",
                expect.objectContaining({ stage: "request", rejected: [555] }),
            );
        });
    });
});
