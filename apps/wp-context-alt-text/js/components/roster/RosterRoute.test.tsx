import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";

import { RosterRoute } from "./RosterRoute";
import type {
    AdminConfig,
    RecognitionObservationAttachment,
    RecognitionObservationSummary,
    RosterData,
    RosterEntry,
    RosterStats,
} from "@/admin/types";

const { useRosterMock } = vi.hoisted(() => ({
    useRosterMock: vi.fn(),
}));

const { useRecognitionObservationsMock } = vi.hoisted(() => ({
    useRecognitionObservationsMock: vi.fn(),
}));

const { dispatchNoticeMock, notifyErrorMock } = vi.hoisted(() => ({
    dispatchNoticeMock: vi.fn(),
    notifyErrorMock: vi.fn(),
}));

vi.mock("@/admin/hooks/useRoster", () => ({
    useRoster: useRosterMock,
}));

vi.mock("@/admin/hooks/useRecognitionObservations", () => ({
    useRecognitionObservations: useRecognitionObservationsMock,
}));

vi.mock("@/admin/notices", () => ({
    dispatchNotice: dispatchNoticeMock,
    notifyError: notifyErrorMock,
}));

const createSampleEntry = (): RosterEntry => ({
    remoteId: "remote-1",
    label: "Alice Example",
    type: "Person",
    status: "SYNCED",
    updatedAt: "2024-01-02T00:00:00.000Z",
    metadata: {},
    referenceImages: [],
    avatarUrl: "https://example.com/avatar.jpg",
    referenceImageCount: 2,
    avatarId: 101,
});

const createSampleStats = (): RosterStats => ({
    total: 1,
    synced: 1,
    local: 0,
    conflicts: 0,
    lastSyncAt: "2024-01-02T00:00:00.000Z",
    lastSyncHuman: "5 minutes",
    metrics: {
        created: 0,
        updated: 0,
        deleted: 0,
        errors: 0,
        conflicts: 0,
    },
});

const createBootstrap = (): RosterData => ({
    entries: [createSampleEntry()],
    stats: createSampleStats(),
});

const createConfig = (): AdminConfig => ({
    endpoints: {
        rosterEntries: "/wp-json/context-alt-text/v1/roster",
        rosterSync: "/wp-json/context-alt-text/v1/roster/sync",
    },
    restNonce: "test-nonce",
    featureFlags: {
        rosterEnabled: true,
    },
});

const createQueryData = (bootstrap: RosterData) => ({
    entries: bootstrap.entries,
    stats: bootstrap.stats,
    total: bootstrap.entries.length,
    page: 1,
    perPage: 20,
    totalPages: 1,
    filters: {
        page: 1,
        perPage: 20,
        search: null,
        status: null,
    },
    syncState: {},
});

const createObservationAttachment = (): RecognitionObservationAttachment => ({
    attachmentId: 42,
    jobId: "job-42",
    updatedAt: 1_704_000_000,
    status: "needs_review",
    summary: {
        total: 1,
        matched: 0,
        needs_review: 1,
    },
    context: {
        filename: "face.jpg",
        imageUrl: "https://example.com/face.jpg",
    },
    observations: [
        {
            observationId: "obs-42",
            label: "Unidentified Person",
            entityType: "Person",
            confidence: 0.91,
            area: 0.12,
            boundingBox: [0.1, 0.2, 0.3, 0.4],
            status: "needs_review",
            source: null,
            match: {
                isMatch: false,
                similarity: 0,
                confidence: 0,
                threshold: 0,
            },
            roster: null,
            candidates: [],
        },
    ],
    confidenceScore: 0.9,
    sourceRemoteId: null,
});

const createObservationSummary = (): RecognitionObservationSummary => ({
    attachments: 1,
    observations: {
        total: 1,
        matched: 0,
        needs_review: 1,
    },
});

// Narrow unknown values to records for safe property access in assertions.
const isRecord = (value: unknown): value is Record<string, unknown> => {
    return value !== null && typeof value === "object";
};

interface SetupOptions {
    hasEndpoint?: boolean;
    isSyncing?: boolean;
    error?: Error | null;
    queryData?: ReturnType<typeof createQueryData>;
    createEntryMock?: ReturnType<typeof vi.fn>;
    updateEntryMock?: ReturnType<typeof vi.fn>;
    deleteEntryMock?: ReturnType<typeof vi.fn>;
    syncRosterMock?: ReturnType<typeof vi.fn>;
    observationItems?: RecognitionObservationAttachment[];
    observationSummary?: RecognitionObservationSummary;
    observationHasEndpoint?: boolean;
    observationError?: Error | null;
    refreshObservationsMock?: ReturnType<typeof vi.fn>;
    updateObservationMock?: ReturnType<typeof vi.fn>;
}

interface SetupResult {
    bootstrap: RosterData;
    config: AdminConfig;
    createEntryMock: ReturnType<typeof vi.fn>;
    updateEntryMock: ReturnType<typeof vi.fn>;
    deleteEntryMock: ReturnType<typeof vi.fn>;
    syncRosterMock: ReturnType<typeof vi.fn>;
    refreshObservationsMock: ReturnType<typeof vi.fn>;
    updateObservationMock: ReturnType<typeof vi.fn>;
}

const setupRosterTest = (options: SetupOptions = {}): SetupResult => {
    const bootstrap = createBootstrap();
    const config = createConfig();
    const queryData = options.queryData ?? createQueryData(bootstrap);
    const observationItems = options.observationItems ?? [createObservationAttachment()];
    const observationSummary = options.observationSummary ?? createObservationSummary();
    const observationHasEndpoint = options.observationHasEndpoint ?? true;
    const observationError = options.observationError ?? null;

    const createEntryMock = options.createEntryMock ?? vi.fn().mockResolvedValue({
        ...createSampleEntry(),
        remoteId: "remote-new",
    });
    const updateEntryMock = options.updateEntryMock ?? vi.fn().mockResolvedValue(createSampleEntry());
    const deleteEntryMock = options.deleteEntryMock ?? vi.fn().mockResolvedValue(true);
    const syncRosterMock = options.syncRosterMock ?? vi.fn().mockResolvedValue(queryData);

    useRosterMock.mockReturnValue({
        query: {
            data: queryData,
            isFetching: false,
            isLoading: false,
            isPending: false,
            status: "success",
            isError: false,
            error: options.error ?? null,
        },
        hasEndpoint: options.hasEndpoint ?? true,
        createEntry: createEntryMock,
        updateEntry: updateEntryMock,
        deleteEntry: deleteEntryMock,
        syncRoster: syncRosterMock,
        isSyncing: options.isSyncing ?? false,
    });

    const observationData = observationError
        ? undefined
        : {
            items: observationItems,
            total: observationItems.length,
            page: 1,
            perPage: observationItems.length > 0 ? observationItems.length : 10,
            totalPages: observationItems.length > 0 ? 1 : 0,
            summary: observationSummary,
        };
    const refreshObservationsMock = options.refreshObservationsMock ?? vi.fn().mockResolvedValue(observationData);
    const updateObservationMock = options.updateObservationMock ?? vi.fn().mockResolvedValue(observationData);

    useRecognitionObservationsMock.mockReturnValue({
        query: {
            data: observationData,
            isFetching: false,
            isLoading: false,
            isPending: false,
            status: observationError ? "error" : "success",
            isError: Boolean(observationError),
            error: observationError,
            refetch: refreshObservationsMock,
        },
        hasEndpoint: observationHasEndpoint,
        canUpdateObservation: true,
        updateObservation: updateObservationMock,
        isUpdating: false,
    });

    return {
        bootstrap,
        config,
        createEntryMock,
        updateEntryMock,
        deleteEntryMock,
        syncRosterMock,
        refreshObservationsMock,
        updateObservationMock,
    };
};

const renderRosterRoute = (
    bootstrap: RosterData,
    config: AdminConfig,
    initialEntries: string[] = ["/roster"],
) =>
    render(
        <MemoryRouter initialEntries={initialEntries}>
            <Routes>
                <Route
                    path="/roster"
                    element={(
                        <RosterRoute
                            bootstrap={bootstrap}
                            config={config}
                        />
                    )}
                />
            </Routes>
        </MemoryRouter>,
    );

beforeEach(() => {
    useRosterMock.mockReset();
    useRecognitionObservationsMock.mockReset();
    dispatchNoticeMock.mockReset();
    notifyErrorMock.mockReset();
});

afterEach(() => {
    vi.restoreAllMocks();
});

describe("RosterRoute", () => {
    it("renders roster stats and entries from bootstrap data", () => {
        const { bootstrap, config } = setupRosterTest();

        renderRosterRoute(bootstrap, config);

        expect(screen.getByRole("heading", { name: /Roster Manager/i })).toBeInTheDocument();
        expect(screen.getByText("Alice Example")).toBeInTheDocument();
        expect(screen.getByText(/remote-1/i)).toBeInTheDocument();
        expect(screen.getByText(/Last synced 5 minutes ago\./i)).toBeInTheDocument();
    });

    it("updates an existing roster entry", async () => {
        const updatedEntry: RosterEntry = {
            ...createSampleEntry(),
            label: "Alice Example Updated",
            type: "Performer",
        };
        const updateEntryMock = vi.fn().mockResolvedValue(updatedEntry);
        const { bootstrap, config, createEntryMock } = setupRosterTest({ updateEntryMock });
        const user = userEvent.setup();

        renderRosterRoute(bootstrap, config);

        await user.click(screen.getByRole("button", { name: /^Edit$/i }));
        expect(await screen.findByRole("heading", { name: /Edit Entry/i })).toBeInTheDocument();

        const labelInput = screen.getByLabelText(/Label/i);
        await user.clear(labelInput);
        await user.type(labelInput, "Alice Example Updated");

        const typeInput = screen.getByLabelText(/Type/i);
        await user.clear(typeInput);
        await user.type(typeInput, "Performer");

        await user.click(screen.getByRole("button", { name: /Save/i }));

        await waitFor(() => expect(updateEntryMock).toHaveBeenCalledTimes(1));
        expect(updateEntryMock).toHaveBeenCalledWith({
            remoteId: "remote-1",
            label: "Alice Example Updated",
            type: "Performer",
            avatarUrl: "https://example.com/avatar.jpg",
            avatarId: 101,
        });
        expect(createEntryMock).not.toHaveBeenCalled();
        expect(dispatchNoticeMock).toHaveBeenCalledWith("success", "Roster entry saved.", {
            id: "cat-roster-save",
        });
    });

    it("creates a new roster entry", async () => {
        const createEntryMock = vi.fn().mockResolvedValue({
            ...createSampleEntry(),
            remoteId: "remote-new",
            label: "New Person",
            type: "Organization",
        });
        const { bootstrap, config, updateEntryMock } = setupRosterTest({ createEntryMock });
        const user = userEvent.setup();

        renderRosterRoute(bootstrap, config);

        await user.click(screen.getByRole("button", { name: /Add Entry/i }));

        const labelInput = screen.getByLabelText(/Label/i);
        await user.clear(labelInput);
        await user.type(labelInput, "New Person");

        const typeInput = screen.getByLabelText(/Type/i);
        await user.clear(typeInput);
        await user.type(typeInput, "Organization");

        await user.click(screen.getByRole("button", { name: /Save/i }));

        await waitFor(() => expect(createEntryMock).toHaveBeenCalledTimes(1));
        expect(createEntryMock).toHaveBeenCalledWith({
            remoteId: null,
            label: "New Person",
            type: "Organization",
            avatarUrl: null,
            avatarId: null,
        });
        expect(updateEntryMock).not.toHaveBeenCalled();
        expect(dispatchNoticeMock).toHaveBeenCalledWith("success", "Roster entry saved.", {
            id: "cat-roster-save",
        });
    });

    it("syncs roster entries from the remote service when triggered", async () => {
        const syncRosterMock = vi.fn().mockResolvedValue(createQueryData(createBootstrap()));
        const { bootstrap, config, refreshObservationsMock } = setupRosterTest({ syncRosterMock });
        const user = userEvent.setup();

        renderRosterRoute(bootstrap, config);

        expect(syncRosterMock).not.toHaveBeenCalled();

        await user.click(screen.getByRole("button", { name: /Sync from Remote/i }));

        await waitFor(() => expect(syncRosterMock).toHaveBeenCalledTimes(1));
        await waitFor(() => expect(refreshObservationsMock).toHaveBeenCalled());
        expect(dispatchNoticeMock).toHaveBeenCalledWith("success", "Roster sync completed.", {
            id: "cat-roster-sync",
        });
    });

    it("deletes a roster entry after confirmation", async () => {
        const deleteEntryMock = vi.fn().mockResolvedValue(true);
        const { bootstrap, config } = setupRosterTest({ deleteEntryMock });
        const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
        const user = userEvent.setup();

        renderRosterRoute(bootstrap, config);

        await user.click(screen.getByRole("button", { name: /Delete/i }));

        await waitFor(() => expect(deleteEntryMock).toHaveBeenCalledWith("remote-1"));
        expect(dispatchNoticeMock).toHaveBeenCalledWith("success", "Roster entry deleted.", {
            id: "cat-roster-delete",
        });

        confirmSpy.mockRestore();
    });

    it("applies a status filter from the query string and clears it", async () => {
        const { bootstrap, config } = setupRosterTest();
        const user = userEvent.setup();

        renderRosterRoute(bootstrap, config, ["/roster?filter=conflict"]);

        expect(await screen.findByText(/Filtered by status: Conflict/i)).toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: /Clear/i }));

        await waitFor(() =>
            expect(screen.queryByText(/Filtered by status: Conflict/i)).not.toBeInTheDocument(),
        );
    });

    it("opens the editor when deep-linking by remoteId", async () => {
        const { bootstrap, config } = setupRosterTest();

        renderRosterRoute(bootstrap, config, ["/roster?remoteId=remote-1"]);

        expect(await screen.findByRole("heading", { name: /Edit Entry/i })).toBeInTheDocument();
        expect(screen.getByDisplayValue("Alice Example")).toBeInTheDocument();
    });

    it("renders an observation prompt when query parameters reference a pending observation", async () => {
        const { bootstrap, config } = setupRosterTest();

        renderRosterRoute(
            bootstrap,
            config,
            [
                "/roster?mode=create&label=Face%20Candidate&observationId=obs-123&attachmentId=42&source=recognition",
            ],
        );

        expect(await screen.findByText(/observation requires roster review/i)).toBeInTheDocument();
        expect(screen.getByText(/obs-123/i)).toBeInTheDocument();
        expect(screen.getByText(/attachment id/i)).toBeInTheDocument();
        expect(screen.getByText(/saving this entry will resolve a recognition observation/i)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /dismiss prompt/i })).toBeInTheDocument();
    });

    it("renders recognition observations awaiting review", async () => {
        const attachment = createObservationAttachment();
        const { bootstrap, config } = setupRosterTest({
            observationItems: [attachment],
            observationSummary: createObservationSummary(),
        });

        renderRosterRoute(bootstrap, config);

        expect(await screen.findByText(/recognition observations awaiting review/i)).toBeInTheDocument();
        expect(screen.getByText(/1 face across 1 attachment requires a roster assignment/i)).toBeInTheDocument();
        expect(screen.getByText("Unidentified Person")).toBeInTheDocument();
        expect(screen.getByAltText(/unidentified person preview/i)).toBeInTheDocument();

        expect(screen.getByRole("button", { name: /create new entry/i })).toBeInTheDocument();
    });

    it("assigns an observation to an existing roster entry", async () => {
        const attachment = createObservationAttachment();
        const { bootstrap, config, updateEntryMock, updateObservationMock, refreshObservationsMock } = setupRosterTest({
            observationItems: [attachment],
            observationSummary: createObservationSummary(),
        });
        const user = userEvent.setup();

        renderRosterRoute(bootstrap, config);

        const select = await screen.findByLabelText(/Select roster entry/i);
        await user.selectOptions(select, "remote-1");

        await user.click(screen.getByRole("button", { name: /Assign existing entry/i }));

        await waitFor(() => expect(updateEntryMock).toHaveBeenCalledTimes(1));
        expect(updateEntryMock).toHaveBeenCalledWith({
            remoteId: "remote-1",
            label: "Alice Example",
            type: "Person",
            resolveObservation: {
                attachmentId: 42,
                observationId: "obs-42",
                status: "matched",
                label: "Alice Example",
                entityType: "Person",
            },
        });
        expect(updateObservationMock).not.toHaveBeenCalled();
        expect(dispatchNoticeMock).toHaveBeenCalledWith(
            "success",
            "Observation matched to Alice Example.",
            { id: "cat-roster-observation-assign-success" },
        );
        expect(refreshObservationsMock).toHaveBeenCalled();
    });

    it("sends observation resolution payload when saving from a prompt", async () => {
        const createEntryMock = vi.fn().mockResolvedValue({
            ...createSampleEntry(),
            remoteId: "remote-new",
            label: "Face Candidate",
            type: "Person",
        });
        const { bootstrap, config } = setupRosterTest({ createEntryMock });
        const user = userEvent.setup();

        renderRosterRoute(
            bootstrap,
            config,
            [
                "/roster?mode=create&label=Face%20Candidate&type=Person&observationId=obs-42&attachmentId=42&source=recognition",
            ],
        );

        expect(await screen.findByText(/observation requires roster review/i)).toBeInTheDocument();
        expect(screen.getAllByText(/match confidence/i).length).toBeGreaterThan(0);

        await user.click(screen.getByRole("button", { name: /Save/i }));

        await waitFor(() => expect(createEntryMock).toHaveBeenCalledTimes(1));
        expect(createEntryMock).toHaveBeenCalledWith(expect.objectContaining({
            label: "Face Candidate",
            type: "Person",
            resolveObservation: {
                attachmentId: 42,
                observationId: "obs-42",
                status: "matched",
                label: "Face Candidate",
                entityType: "Person",
            },
            // Validate referenceImages below to avoid unsafe matcher types
        }));

        // Further assert referenceImages and nested metadata without unsafe any by narrowing runtime types
        const firstCallUnknown: unknown = createEntryMock.mock.calls[0]?.[0];
        expect(firstCallUnknown).toBeDefined();
        if (isRecord(firstCallUnknown)) {
            const imagesUnknown = firstCallUnknown.referenceImages ?? null;
            expect(Array.isArray(imagesUnknown)).toBe(true);
            const images: unknown[] = Array.isArray(imagesUnknown) ? (imagesUnknown as unknown[]) : [];
            if (images.length > 0) {
                const firstImage = images[0];
                if (isRecord(firstImage)) {
                    const metadataUnknown = firstImage.metadata ?? null;
                    expect(isRecord(metadataUnknown)).toBe(true);
                    if (isRecord(metadataUnknown)) {
                        expect(metadataUnknown).toMatchObject({
                            source: "recognition",
                            observationId: "obs-42",
                            confidence: 0.91,
                            area: 0.12,
                            label: "Face Candidate",
                            entityType: "Person",
                        });
                    }
                }
            }
        }

        await waitFor(() =>
            expect(screen.queryByText(/observation requires roster review/i)).not.toBeInTheDocument(),
        );
        expect(dispatchNoticeMock).toHaveBeenCalledWith("success", "Roster entry saved.", {
            id: "cat-roster-save",
        });
    });

    it("surfaces query errors via admin notices", async () => {
        const error = new Error("Failed to load roster");
        const { bootstrap, config } = setupRosterTest({ error });

        renderRosterRoute(bootstrap, config);

        await waitFor(() =>
            expect(notifyErrorMock).toHaveBeenCalledWith("Failed to load roster", { id: "cat-roster-error" }),
        );
    });
});
