/**
 * Integration tests for useRosterState and useObservationWorkflow hooks
 *
 * These tests verify that both hooks work together correctly in realistic scenarios,
 * simulating how they will be used together in RosterRoute.tsx.
 */
/* eslint-disable @typescript-eslint/no-unsafe-assignment */
/* eslint-disable @typescript-eslint/no-explicit-any */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRosterState } from "./useRosterState";
import { useObservationWorkflow } from "./useObservationWorkflow";
import type {
    AdminConfig,
    RosterEntry,
    RecognitionObservationRecord,
    RecognitionObservationAttachment,
} from "@/admin/types";
import type { UseRecognitionObservationsResult } from "./useRecognitionObservations";
import * as useRecognitionObservationsModule from "./useRecognitionObservations";
import * as noticesModule from "@/admin/notices";

// Mock dependencies
vi.mock("./useRecognitionObservations");
vi.mock("@/admin/notices");

const createMockObservationsResult = (
    overrides?: Partial<UseRecognitionObservationsResult>,
): UseRecognitionObservationsResult =>
    ({
        query: {
            data: undefined,
            error: null,
            isFetching: false,
            isLoading: false,
            refetch: vi.fn(),
        } as any,
        hasEndpoint: true,
        canUpdateObservation: true,
        updateObservation: vi.fn(),
        isUpdating: false,
        retryRecognition: vi.fn(),
        isRetrying: false,
        ...overrides,
    }) as UseRecognitionObservationsResult;

describe("useRosterState + useObservationWorkflow Integration", () => {
    const mockConfig: AdminConfig = {
        endpoints: {
            rosterEntries: "/wp-json/cat/v1/roster",
            recognitionObservations: "/wp-json/cat/v1/observations",
        },
        featureFlags: {},
        settings: {
            recognition: {
                canManage: true,
            },
        },
    };

    const mockEntries: RosterEntry[] = [
        {
            remoteId: "person-1",
            label: "Alice Johnson",
            type: "person",
            status: "SYNCED",
            updatedAt: "2025-10-18T00:00:00Z",
            metadata: {},
            referenceImages: [],
            avatarUrl: null,
            avatarId: null,
            referenceImageCount: 0,
        },
        {
            remoteId: "person-2",
            label: "Bob Smith",
            type: "person",
            status: "SYNCED",
            updatedAt: "2025-10-18T00:00:00Z",
            metadata: {},
            referenceImages: [],
            avatarUrl: null,
            avatarId: null,
            referenceImageCount: 0,
        },
        {
            remoteId: "brand-1",
            label: "Acme Corp",
            type: "brand",
            status: "LOCAL",
            updatedAt: "2025-10-18T00:00:00Z",
            metadata: {},
            referenceImages: [],
            avatarUrl: null,
            avatarId: null,
            referenceImageCount: 0,
        },
    ];

    const mockUpdateEntry = vi.fn();
    const mockRefetch = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
        mockUpdateEntry.mockResolvedValue(undefined);
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    describe("Workflow: Search and Filter with Observations", () => {
        it("filters roster entries and observations remain independent", () => {
            const mockObservationData = {
                items: [
                    {
                        attachmentId: 100,
                        jobId: "job-1",
                        updatedAt: Date.now(),
                        status: "needs_review" as const,
                        summary: { total: 1, matched: 0, needs_review: 1 },
                        observations: [
                            {
                                observationId: "obs-1",
                                label: "Alice Johnson",
                                entityType: "person",
                                confidence: 0.95,
                                status: "needs_review" as const,
                                candidates: [],
                                roster: null,
                                area: 0.25,
                                boundingBox: [100, 100, 200, 200],
                                source: null,
                                match: {
                                    isMatch: false,
                                    similarity: 0.95,
                                    confidence: 0.95,
                                    threshold: 0.85,
                                },
                            },
                        ],
                        context: {},
                        confidenceScore: 0.95,
                        sourceRemoteId: null,
                    },
                ],
                summary: {
                    attachments: 1,
                    observations: { total: 1, matched: 0, needs_review: 1 },
                },
            };

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: mockObservationData,
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result: rosterState } = renderHook(() => useRosterState({ searchDebounceMs: 0 }));
            const { result: observationWorkflow } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            // Initial state
            expect(rosterState.current.state.searchInput).toBe("");
            expect(observationWorkflow.current.observationItems).toHaveLength(1);

            // Update search in roster state (debounce disabled so it updates immediately)
            act(() => {
                rosterState.current.actions.setSearchInput("Alice");
            });

            expect(rosterState.current.state.searchInput).toBe("Alice");
            expect(rosterState.current.filters.search).toBe("Alice");

            // Observation workflow is unaffected by roster search
            expect(observationWorkflow.current.observationItems).toHaveLength(1);
            expect(observationWorkflow.current.observationSummary.attachments).toBe(1);
        });

        it("status filter changes reset pagination", () => {
            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult(),
            );

            const { result } = renderHook(() => useRosterState({ searchDebounceMs: 0 }));

            // Navigate to page 3
            act(() => {
                result.current.actions.setPage(3);
            });

            expect(result.current.state.page).toBe(3);

            // Change status filter - should reset page
            act(() => {
                result.current.actions.setStatusFilter("LOCAL");
            });

            expect(result.current.state.statusFilter).toBe("LOCAL");
            expect(result.current.state.page).toBe(1); // Reset to page 1
        });
    });

    describe("Workflow: Observation Assignment", () => {
        it("assigns observation to roster entry and refetches", async () => {
            const mockObservationRecord: RecognitionObservationRecord = {
                observationId: "obs-123",
                label: "Alice Johnson",
                entityType: "person",
                confidence: 0.95,
                status: "needs_review",
                candidates: [],
                roster: null,
                area: 0.25,
                boundingBox: [100, 100, 200, 200],
                source: null,
                match: {
                    isMatch: false,
                    similarity: 0.95,
                    confidence: 0.95,
                    threshold: 0.85,
                },
            };

            const mockAttachment: RecognitionObservationAttachment = {
                attachmentId: 456,
                jobId: "job-123",
                updatedAt: Date.now(),
                status: "needs_review",
                summary: { total: 1, matched: 0, needs_review: 1 },
                observations: [mockObservationRecord],
                context: {},
                confidenceScore: 0.95,
                sourceRemoteId: null,
            };

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: {
                            items: [mockAttachment],
                            summary: {
                                attachments: 1,
                                observations: { total: 1, matched: 0, needs_review: 1 },
                            },
                        },
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result: rosterState } = renderHook(() => useRosterState({}));
            const { result: observationWorkflow } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            // Verify observation index is built
            expect(observationWorkflow.current.observationIndex.size).toBe(1);
            expect(observationWorkflow.current.observationIndex.has("obs-123")).toBe(true);

            // Simulate assignment workflow
            await act(async () => {
                await observationWorkflow.current.handleAssignToRoster(
                    mockObservationRecord,
                    mockAttachment,
                    "person-1",
                );
            });

            // Verify updateEntry was called correctly
            expect(mockUpdateEntry).toHaveBeenCalledWith({
                remoteId: "person-1",
                label: "Alice Johnson",
                type: "person",
                resolveObservation: {
                    attachmentId: 456,
                    observationId: "obs-123",
                    status: "matched",
                    label: "Alice Johnson",
                    entityType: "person",
                },
            });

            // Verify refetch was called
            expect(mockRefetch).toHaveBeenCalled();

            // Verify success notice
            expect(noticesModule.dispatchNotice).toHaveBeenCalledWith(
                "success",
                expect.stringContaining("Alice Johnson"),
                { id: "cat-roster-observation-assign-success" },
            );

            // Roster state remains independent
            expect(rosterState.current.state.page).toBe(1);
        });

        it("handles observation assignment with observation prompt state", async () => {
            const mockObservationRecord: RecognitionObservationRecord = {
                observationId: "obs-prompt",
                label: "Unknown Person",
                entityType: "person",
                confidence: 0.75,
                status: "needs_review",
                candidates: [],
                roster: null,
                area: 0.2,
                boundingBox: [50, 50, 150, 150],
                source: null,
                match: {
                    isMatch: false,
                    similarity: 0.75,
                    confidence: 0.75,
                    threshold: 0.85,
                },
            };

            const mockAttachment: RecognitionObservationAttachment = {
                attachmentId: 789,
                jobId: "job-456",
                updatedAt: Date.now(),
                status: "needs_review",
                summary: { total: 1, matched: 0, needs_review: 1 },
                observations: [mockObservationRecord],
                context: { imageUrl: "https://example.com/image.jpg" },
                confidenceScore: 0.75,
                sourceRemoteId: null,
            };

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: {
                            items: [mockAttachment],
                            summary: {
                                attachments: 1,
                                observations: { total: 1, matched: 0, needs_review: 1 },
                            },
                        },
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result: rosterState } = renderHook(() => useRosterState({}));
            const { result: observationWorkflow } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            // Simulate observation prompt state in roster
            act(() => {
                rosterState.current.actions.setObservationPrompt({
                    observationId: "obs-prompt",
                    attachmentId: 789,
                    label: "Unknown Person",
                    source: "https://example.com/image.jpg",
                });
            });

            expect(rosterState.current.state.observationPrompt).toBeDefined();
            expect(rosterState.current.state.observationPrompt?.observationId).toBe("obs-prompt");

            // Look up observation in index
            const indexEntry = observationWorkflow.current.observationIndex.get("obs-prompt");
            expect(indexEntry).toBeDefined();
            expect(indexEntry?.attachment.attachmentId).toBe(789);

            // Assign observation
            await act(async () => {
                await observationWorkflow.current.handleAssignToRoster(
                    mockObservationRecord,
                    mockAttachment,
                    "person-2",
                );
            });

            // Verify assignment
            expect(mockUpdateEntry).toHaveBeenCalledWith({
                remoteId: "person-2",
                label: "Bob Smith",
                type: "person",
                resolveObservation: {
                    attachmentId: 789,
                    observationId: "obs-prompt",
                    status: "matched",
                    label: "Bob Smith",
                    entityType: "person",
                },
            });

            // Clear observation prompt after successful assignment
            act(() => {
                rosterState.current.actions.setObservationPrompt(null);
            });

            expect(rosterState.current.state.observationPrompt).toBeNull();
        });
    });

    describe("Workflow: Form Submission with Observation", () => {
        it("coordinates form state and observation assignment", async () => {
            const mockObservationRecord: RecognitionObservationRecord = {
                observationId: "obs-new-entry",
                label: "New Person",
                entityType: "person",
                confidence: 0.88,
                status: "needs_review",
                candidates: [],
                roster: null,
                area: 0.3,
                boundingBox: [10, 10, 100, 100],
                source: null,
                match: {
                    isMatch: false,
                    similarity: 0.88,
                    confidence: 0.88,
                    threshold: 0.85,
                },
            };

            const mockAttachment: RecognitionObservationAttachment = {
                attachmentId: 999,
                jobId: "job-789",
                updatedAt: Date.now(),
                status: "needs_review",
                summary: { total: 1, matched: 0, needs_review: 1 },
                observations: [mockObservationRecord],
                context: {},
                confidenceScore: 0.88,
                sourceRemoteId: null,
            };

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: {
                            items: [mockAttachment],
                            summary: {
                                attachments: 1,
                                observations: { total: 1, matched: 0, needs_review: 1 },
                            },
                        },
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result: rosterState } = renderHook(() => useRosterState({ searchDebounceMs: 0 }));

            // Start with initial entries
            const { result: observationWorkflow, rerender } = renderHook(
                ({ entries }) =>
                    useObservationWorkflow({
                        config: mockConfig,
                        entries,
                        updateEntry: mockUpdateEntry,
                    }),
                { initialProps: { entries: mockEntries } },
            );

            // Start editing (create new entry)
            act(() => {
                rosterState.current.actions.setEditing(null); // null = create new
                rosterState.current.actions.setDraftValues({ label: "Charlie Brown", type: "person" });
                rosterState.current.actions.setObservationPrompt({
                    observationId: "obs-new-entry",
                    attachmentId: 999,
                    label: "New Person",
                    source: null,
                });
            });

            expect(rosterState.current.state.editing).toBeNull();
            expect(rosterState.current.state.draftValues?.label).toBe("Charlie Brown");
            expect(rosterState.current.state.draftValues?.type).toBe("person");
            expect(rosterState.current.state.observationPrompt).toBeDefined();

            // Simulate form submission - add new entry to the entries array
            const newRemoteId = "person-3";
            const newEntry: RosterEntry = {
                remoteId: newRemoteId,
                label: "Charlie Brown",
                type: "person",
                status: "LOCAL",
                updatedAt: "2025-10-18T00:00:00Z",
                metadata: {},
                referenceImages: [],
                avatarUrl: null,
                avatarId: null,
                referenceImageCount: 0,
            };

            const updatedEntries = [...mockEntries, newEntry];

            // Rerender with updated entries
            rerender({ entries: updatedEntries });

            // Then assign observation to the new entry
            await act(async () => {
                await observationWorkflow.current.handleAssignToRoster(
                    mockObservationRecord,
                    mockAttachment,
                    newRemoteId,
                );
            });

            // Verify updateEntry was called
            expect(mockUpdateEntry).toHaveBeenCalledWith({
                remoteId: newRemoteId,
                label: "Charlie Brown",
                type: "person",
                resolveObservation: {
                    attachmentId: 999,
                    observationId: "obs-new-entry",
                    status: "matched",
                    label: "Charlie Brown",
                    entityType: "person",
                },
            });

            // Clean up form state after successful submission
            act(() => {
                rosterState.current.actions.resetForm();
                rosterState.current.actions.setObservationPrompt(null);
            });

            expect(rosterState.current.state.observationPrompt).toBeNull();
            expect(rosterState.current.state.draftValues).toBeNull();
        });
    });

    describe("Workflow: Error Handling", () => {
        it("handles observation assignment errors without affecting roster state", async () => {
            const mockObservationRecord: RecognitionObservationRecord = {
                observationId: "obs-error",
                label: "Error Test",
                entityType: "person",
                confidence: 0.9,
                status: "needs_review",
                candidates: [],
                roster: null,
                area: 0.25,
                boundingBox: [100, 100, 200, 200],
                source: null,
                match: {
                    isMatch: false,
                    similarity: 0.9,
                    confidence: 0.9,
                    threshold: 0.85,
                },
            };

            const mockAttachment: RecognitionObservationAttachment = {
                attachmentId: 111,
                jobId: "job-error",
                updatedAt: Date.now(),
                status: "needs_review",
                summary: { total: 1, matched: 0, needs_review: 1 },
                observations: [mockObservationRecord],
                context: {},
                confidenceScore: 0.9,
                sourceRemoteId: null,
            };

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: {
                            items: [mockAttachment],
                            summary: {
                                attachments: 1,
                                observations: { total: 1, matched: 0, needs_review: 1 },
                            },
                        },
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            // Mock updateEntry to fail
            mockUpdateEntry.mockRejectedValueOnce(new Error("Network error"));

            const { result: rosterState } = renderHook(() => useRosterState({}));
            const { result: observationWorkflow } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            // Set up some roster state
            act(() => {
                rosterState.current.actions.setSearchInput("Test");
                rosterState.current.actions.setPage(2);
            });

            const initialState = { ...rosterState.current.state };

            // Attempt assignment (should fail)
            await act(async () => {
                await observationWorkflow.current.handleAssignToRoster(
                    mockObservationRecord,
                    mockAttachment,
                    "person-1",
                );
            });

            // Verify error was displayed
            expect(noticesModule.notifyError).toHaveBeenCalledWith("Network error", {
                id: "cat-roster-observation-assign-error",
            });

            // Verify roster state was NOT affected by the error
            expect(rosterState.current.state.searchInput).toBe(initialState.searchInput);
            expect(rosterState.current.state.page).toBe(initialState.page);
        });

        it("handles observation loading state independently from roster state", () => {
            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: undefined,
                        error: null,
                        isFetching: true,
                        isLoading: true,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result: rosterState } = renderHook(() => useRosterState({}));
            const { result: observationWorkflow } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            // Observation is loading
            expect(observationWorkflow.current.observationsLoading).toBe(true);
            expect(observationWorkflow.current.observationItems).toHaveLength(0);

            // Roster state can still be manipulated
            act(() => {
                rosterState.current.actions.setSearchInput("Test");
                rosterState.current.actions.setStatusFilter("SYNCED");
            });

            expect(rosterState.current.state.searchInput).toBe("Test");
            expect(rosterState.current.state.statusFilter).toBe("SYNCED");
        });
    });

    describe("Workflow: Complex State Coordination", () => {
        it("handles pagination, search, and observation assignment together", async () => {
            const mockObservationRecord: RecognitionObservationRecord = {
                observationId: "obs-complex",
                label: "Complex Test",
                entityType: "person",
                confidence: 0.92,
                status: "needs_review",
                candidates: [],
                roster: null,
                area: 0.28,
                boundingBox: [120, 120, 220, 220],
                source: null,
                match: {
                    isMatch: false,
                    similarity: 0.92,
                    confidence: 0.92,
                    threshold: 0.85,
                },
            };

            const mockAttachment: RecognitionObservationAttachment = {
                attachmentId: 555,
                jobId: "job-complex",
                updatedAt: Date.now(),
                status: "needs_review",
                summary: { total: 1, matched: 0, needs_review: 1 },
                observations: [mockObservationRecord],
                context: {},
                confidenceScore: 0.92,
                sourceRemoteId: null,
            };

            vi.mocked(useRecognitionObservationsModule.useRecognitionObservations).mockReturnValue(
                createMockObservationsResult({
                    query: {
                        data: {
                            items: [mockAttachment],
                            summary: {
                                attachments: 1,
                                observations: { total: 1, matched: 0, needs_review: 1 },
                            },
                        },
                        error: null,
                        isFetching: false,
                        isLoading: false,
                        refetch: mockRefetch,
                    } as any,
                }),
            );

            const { result: rosterState } = renderHook(() => useRosterState({ searchDebounceMs: 0 }));
            const { result: observationWorkflow } = renderHook(() =>
                useObservationWorkflow({
                    config: mockConfig,
                    entries: mockEntries,
                    updateEntry: mockUpdateEntry,
                }),
            );

            // User performs search (debounce disabled so it updates immediately)
            act(() => {
                rosterState.current.actions.setSearchInput("Alice");
            });

            // User navigates to page 2
            act(() => {
                rosterState.current.actions.setPage(2);
            });

            // User changes per page
            act(() => {
                rosterState.current.actions.setPerPage(50);
            });

            expect(rosterState.current.state.page).toBe(2);
            expect(rosterState.current.state.perPage).toBe(50);
            expect(rosterState.current.filters.search).toBe("Alice");

            // User assigns an observation
            await act(async () => {
                await observationWorkflow.current.handleAssignToRoster(
                    mockObservationRecord,
                    mockAttachment,
                    "person-1",
                );
            });

            // Observation assigned successfully
            expect(mockUpdateEntry).toHaveBeenCalled();
            expect(mockRefetch).toHaveBeenCalled();

            // Roster state remains intact
            expect(rosterState.current.state.page).toBe(2);
            expect(rosterState.current.state.perPage).toBe(50);
            expect(rosterState.current.filters.search).toBe("Alice");
        });
    });
});
