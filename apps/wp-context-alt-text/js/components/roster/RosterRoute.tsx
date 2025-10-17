import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { __, sprintf, _n } from "@wordpress/i18n";

import type {
    AdminConfig,
    RosterData,
    RosterEntry,
    RecognitionObservationAttachment,
    RecognitionObservationCandidate,
    RecognitionObservationRecord,
    RecognitionObservationSummary,
} from "@/admin/types";
import { useRoster, type RosterFilters, type RosterFormValues } from "@/admin/hooks/useRoster";
import { useRecognitionObservations } from "@/admin/hooks/useRecognitionObservations";
import { dispatchNotice, notifyError } from "@/admin/notices";

// Local helpers (stubs or re-exports expected elsewhere in the app)
const DEFAULT_OBSERVATION_SUMMARY: RecognitionObservationSummary = {
    attachments: 0,
    observations: { total: 0, matched: 0, needs_review: 0 },
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
    value !== null && typeof value === "object";

interface ObservationPromptState {
    observationId: string;
    attachmentId: number | null;
    source: string | null;
    remoteId?: string | null;
    label?: string | null;
}

interface RosterRouteProps {
    bootstrap: RosterData;
    config: AdminConfig;
}

const isFiniteNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

const normalizeConfidence = (value: unknown): number | null => {
    if (!isFiniteNumber(value)) {
        return null;
    }

    const normalized = value > 1 ? value / 100 : value;
    return normalized >= 0 ? normalized : null;
};

const getTopCandidate = (record: RecognitionObservationRecord): RecognitionObservationCandidate | null => {
    if (!record || !Array.isArray(record.candidates) || record.candidates.length === 0) {
        return null;
    }

    const sorted = [...record.candidates].filter(Boolean).sort((a, b) => {
        const meetsThresholdDelta = Number(b.meetsThreshold) - Number(a.meetsThreshold);
        if (meetsThresholdDelta !== 0) {
            return meetsThresholdDelta;
        }

        const bConfidence = normalizeConfidence(b.confidence) ?? -Infinity;
        const aConfidence = normalizeConfidence(a.confidence) ?? -Infinity;
        if (bConfidence !== aConfidence) {
            return bConfidence - aConfidence;
        }

        const bSimilarity = isFiniteNumber(b.similarity) ? b.similarity : -Infinity;
        const aSimilarity = isFiniteNumber(a.similarity) ? a.similarity : -Infinity;
        return bSimilarity - aSimilarity;
    });

    return sorted[0] ?? null;
};

const resolveSuggestedMatchLabel = (
    record: RecognitionObservationRecord,
    lookup: Map<string, RosterEntry>,
    top: RecognitionObservationCandidate | null,
): string | null => {
    const labelFromEntry = (remoteId: string | null | undefined): string | null => {
        if (!remoteId) {
            return null;
        }
        const entry = lookup.get(remoteId);
        if (!entry) {
            return null;
        }
        if (entry.label && entry.type) {
            return `${entry.label} (${entry.type})`;
        }

        return entry.label ?? entry.remoteId ?? null;
    };

    const rosterRemote = record?.roster?.remoteId ?? null;
    const rosterLabel = record?.roster?.displayName ?? record?.roster?.name ?? null;

    return (
        labelFromEntry(rosterRemote)
        ?? rosterLabel
        ?? labelFromEntry(top?.remoteId ?? null)
        ?? (top?.name?.trim() ? top.name : null)
        ?? (top?.remoteId ?? null)
        ?? (record?.label?.trim() ? record.label : null)
        ?? null
    );
};

const getRosterConfidenceValue = (
    record: RecognitionObservationRecord,
    top: RecognitionObservationCandidate | null,
): number | null => {
    // Only show confidence if there's an actual roster match or valid candidates
    const hasRosterMatch = Boolean(record?.roster?.remoteId) || Boolean(record?.match?.isMatch);
    const hasValidCandidates = Array.isArray(record?.candidates) && record.candidates.length > 0;

    if (!hasRosterMatch && !hasValidCandidates) {
        return null;
    }

    // Prioritize roster similarity (recognition match score) over detection confidence
    const matchSimilarity = normalizeConfidence(record?.match?.similarity);
    if (matchSimilarity !== null && matchSimilarity > 0) {
        return matchSimilarity;
    }

    const candidates = [
        normalizeConfidence(record?.match?.confidence),
        normalizeConfidence(record?.matchConfidence),
        normalizeConfidence(top?.similarity),
        normalizeConfidence(top?.confidence),
    ];

    for (const value of candidates) {
        if (value !== null && value > 0) {
            return value;
        }
    }

    return null;
};

const formatPercentage = (value: number | null | undefined): string | null => {
    if (!isFiniteNumber(value)) {
        return null;
    }

    const normalized = value > 1 ? value / 100 : value;

    if (typeof Intl !== "undefined" && Intl.NumberFormat) {
        const formatter = new Intl.NumberFormat(undefined, {
            style: "percent",
            maximumFractionDigits: normalized >= 0.995 ? 0 : normalized >= 0.1 ? 1 : 2,
        });
        return formatter.format(normalized);
    }

    const percent = Math.round(normalized * 100);
    return `${percent}%`;
};

const resolveSuggestedRemoteId = (
    record: RecognitionObservationRecord,
    lookup: Map<string, RosterEntry>,
    top: RecognitionObservationCandidate | null,
): string | null => {
    const fromRoster = record?.roster?.remoteId ?? null;
    if (fromRoster && (lookup.has(fromRoster) || fromRoster.trim() !== "")) {
        return fromRoster;
    }

    const candidateRemote = top?.remoteId ?? null;
    if (candidateRemote && (lookup.has(candidateRemote) || candidateRemote.trim() !== "")) {
        return candidateRemote;
    }

    return null;
};

const getSelectedRemoteId = (
    record: RecognitionObservationRecord,
    selection: Record<string, string>,
    suggested: string | null,
): string => {
    const selected = record?.observationId ? selection[record.observationId] : undefined;
    if (selected && selected.trim() !== "") {
        return selected;
    }

    return suggested ?? "";
};

const getDetectionConfidenceValue = (record: RecognitionObservationRecord): number | null => {
    const detection = normalizeConfidence(record?.detectionConfidence);
    if (detection !== null) {
        return detection;
    }

    return normalizeConfidence(record?.confidence);
};

const buildObservationSearchParams = (
    record: RecognitionObservationRecord,
    attachmentId: number | null,
): URLSearchParams => {
    const baseSearch = typeof window !== "undefined" ? window.location.search : "";
    const params = new URLSearchParams(baseSearch || undefined);

    if (!record?.observationId) {
        return params;
    }

    params.set("observationId", record.observationId);
    if (attachmentId && Number.isFinite(attachmentId)) {
        params.set("attachmentId", String(attachmentId));
    } else {
        params.delete("attachmentId");
    }

    const mode = record?.roster?.remoteId ? "edit" : "create";
    params.set("mode", mode);

    if (record?.label?.trim()) {
        params.set("label", record.label.trim());
    } else {
        params.delete("label");
    }

    if (record?.entityType?.trim()) {
        params.set("type", record.entityType.trim());
    } else {
        params.delete("type");
    }

    const remoteId = record?.roster?.remoteId ?? null;
    if (remoteId && remoteId.trim() !== "") {
        params.set("remoteId", remoteId);
    } else {
        params.delete("remoteId");
    }

    params.set("source", "recognition");

    return params;
};

const getWpMedia = (): ((options: Record<string, unknown>) => MediaFrame) | undefined => {
    const root = typeof window !== "undefined"
        ? window
        : typeof globalThis !== "undefined"
            ? (globalThis as typeof globalThis & { wp?: { media?: unknown } })
            : undefined;

    const mediaFactory = root?.wp && typeof root.wp === "object" ? (root.wp as { media?: unknown }).media : undefined;

    return typeof mediaFactory === "function" ? mediaFactory : undefined;
};

// The main Roster route component is defined below in full.

const SEARCH_DEBOUNCE_MS = 300;

interface MediaFrameState {
    get: (key: string) => unknown;
}

interface MediaFrame {
    on: (event: string, callback: () => void) => void;
    off?: (event: string) => void;
    open: () => void;
    state: () => { get: (key: string) => unknown } | MediaFrameState | undefined;
}

const RosterObservationsPanel = ({
    attachments,
    summary,
    isLoading,
    error,
    hasEndpoint,
    entries,
    onCreate,
    onAssign,
    onRefresh,
}: RosterObservationsPanelProps): React.JSX.Element => {
    const pendingCount = Math.max(0, summary.observations.needs_review);
    const attachmentCount = Math.max(0, summary.attachments);

    const assignableEntries = React.useMemo(
        () => entries.filter((entry) => entry.remoteId && entry.remoteId.trim() !== ""),
        [entries],
    );

    const assignableEntryLookup = React.useMemo(() => {
        const lookup = new Map<string, RosterEntry>();
        for (const entry of assignableEntries) {
            if (entry.remoteId) {
                lookup.set(entry.remoteId, entry);
            }
        }
        return lookup;
    }, [assignableEntries]);

    const [selection, setSelection] = React.useState<Record<string, string>>({});
    const [assigningId, setAssigningId] = React.useState<string | null>(null);

    const pendingAttachments = React.useMemo(
        () =>
            attachments
                .map((attachment) => {
                    const pending = attachment.observations.filter((record) => record.status === "needs_review");
                    return { attachment, pending };
                })
                .filter((item) => item.pending.length > 0),
        [attachments],
    );

    React.useEffect(() => {
        const validObservationIds = new Set<string>();
        for (const attachment of attachments) {
            for (const record of attachment.observations) {
                if (record.status !== "needs_review") continue;
                if (record.observationId) validObservationIds.add(record.observationId);
            }
        }
        setSelection((current) => {
            const next = { ...current };
            let changed = false;
            for (const key of Object.keys(next)) {
                if (!validObservationIds.has(key)) {
                    delete next[key];
                    changed = true;
                }
            }
            return changed ? next : current;
        });
    }, [attachments]);

    const handleAssign = React.useCallback(
        async (
            record: RecognitionObservationRecord,
            attachment: RecognitionObservationAttachment,
            suggestedRemoteId: string | null,
        ) => {
            const remoteId = getSelectedRemoteId(record, selection, suggestedRemoteId);
            if (!remoteId) return;

            try {
                setAssigningId(record.observationId ?? null);
                // onAssign can be sync or async; normalize to a Promise to satisfy lint and ensure proper sequencing
                await Promise.resolve(onAssign(record, attachment, remoteId));
                setSelection((current) => {
                    const next = { ...current };
                    delete next[record.observationId ?? ""];
                    return next;
                });
            } finally {
                setAssigningId(null);
            }
        },
        [onAssign, selection],
    );

    return (
        <section className="cat-roster__observations" aria-live="polite">
            {!hasEndpoint ? (
                <>
                    <h3>{__("Recognition observations", "context-alt-text")}</h3>
                    <p className="cat-roster__observations-status">
                        {__(
                            "Recognition observations are unavailable. Enable the recognition feature flag to manage detected faces.",
                            "context-alt-text",
                        )}
                    </p>
                </>
            ) : (
                <>
                    <header className="cat-roster__observations-header">
                        <div>
                            <h3>{__("Recognition observations awaiting review", "context-alt-text")}</h3>
                            <p>
                                {pendingCount > 0
                                    ? sprintf(
                                        _n(
                                            "%1$d face across %2$d attachment requires a roster assignment.",
                                            "%1$d faces across %2$d attachments require roster assignments.",
                                            pendingCount,
                                            "context-alt-text",
                                        ),
                                        pendingCount,
                                        attachmentCount,
                                    )
                                    : __("Faces detected by recognition will appear here when they require review.", "context-alt-text")}
                            </p>
                        </div>
                        <div className="cat-roster__observations-actions">
                            <button
                                type="button"
                                className="cat-button cat-button--subtle"
                                onClick={() => void onRefresh()}
                                disabled={isLoading}
                            >
                                {isLoading ? __("Re-running…", "context-alt-text") : __("Re-run recognition", "context-alt-text")}
                            </button>
                        </div>
                    </header>

                    {error && (
                        <div className="cat-alert cat-alert--error" role="alert">
                            <span>{error.message}</span>
                        </div>
                    )}

                    {isLoading && pendingAttachments.length === 0 ? (
                        <p className="cat-roster__observations-status">{__("Loading observations…", "context-alt-text")}</p>
                    ) : null}

                    {!isLoading && pendingAttachments.length === 0 ? (
                        <p className="cat-roster__observations-status">
                            {__("No recognition observations require review right now.", "context-alt-text")}
                        </p>
                    ) : null}

                    {pendingAttachments.length > 0 && (
                        <ul className="cat-roster__observations-list">
                            {pendingAttachments.map(({ attachment, pending }) => {
                                const attachmentId = attachment.attachmentId;
                                const displayName =
                                    attachment.context?.filename ??
                                    (attachmentId
                                        ? sprintf(
                                            __("Attachment %d", "context-alt-text"),
                                            attachmentId,
                                        )
                                        : __("Media item", "context-alt-text"));
                                const unresolved = pending.length;

                                return (
                                    <li key={`${attachmentId ?? "unknown"}-${attachment.jobId ?? "job"}`} className="cat-roster__observations-item">
                                        <div className="cat-roster__observations-attachment">
                                            <div>
                                                <strong>{displayName}</strong>
                                                {attachment.context?.imageUrl && (
                                                    <a
                                                        href={attachment.context.imageUrl}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className="cat-roster__observations-link"
                                                    >
                                                        {__("Open", "context-alt-text")}
                                                    </a>
                                                )}
                                            </div>
                                            <span className="cat-roster__observations-count">
                                                {sprintf(
                                                    _n(
                                                        "%d face needs review",
                                                        "%d faces need review",
                                                        unresolved,
                                                        "context-alt-text",
                                                    ),
                                                    unresolved,
                                                )}
                                            </span>
                                        </div>
                                        <ul className="cat-roster__observations-faces">
                                            {pending.map((record) => {
                                                const displayLabel = record.label || record.entityType || __("Observation", "context-alt-text");
                                                const topCandidate = getTopCandidate(record);
                                                const rosterMatch = resolveSuggestedMatchLabel(record, assignableEntryLookup, topCandidate);
                                                const rosterConfidenceValue = getRosterConfidenceValue(record, topCandidate);
                                                const confidenceDisplay = formatPercentage(rosterConfidenceValue);
                                                const suggestedRemoteId = resolveSuggestedRemoteId(record, assignableEntryLookup, topCandidate);
                                                const selectedRemoteId = getSelectedRemoteId(record, selection, suggestedRemoteId);
                                                const isAssigning = assigningId === (record.observationId ?? null);

                                                return (
                                                    <li key={record.observationId} className="cat-roster__observations-face">
                                                        <ObservationPreview record={record} attachment={attachment} />
                                                        <div className="cat-roster__observations-face-details">
                                                            <span className="cat-roster__observations-label">{displayLabel}</span>
                                                            {rosterMatch ? (
                                                                <span className="cat-roster__observations-meta">
                                                                    {sprintf(
                                                                        __("Suggested match: %s", "context-alt-text"),
                                                                        rosterMatch,
                                                                    )}
                                                                </span>
                                                            ) : null}
                                                            {confidenceDisplay && (
                                                                <span className="cat-roster__observations-meta">
                                                                    {sprintf(
                                                                        __("Match confidence %s", "context-alt-text"),
                                                                        confidenceDisplay,
                                                                    )}
                                                                </span>
                                                            )}
                                                        </div>
                                                        <div className="cat-roster__observations-face-actions">
                                                            <label className="screen-reader-text" htmlFor={`cat-roster-observation-${record.observationId}-select`}>
                                                                {__("Select roster entry", "context-alt-text")}
                                                            </label>
                                                            <select
                                                                id={`cat-roster-observation-${record.observationId}-select`}
                                                                value={selectedRemoteId}
                                                                onChange={(event) =>
                                                                    setSelection((current) => ({
                                                                        ...current,
                                                                        [record.observationId ?? ""]: event.target.value,
                                                                    }))
                                                                }
                                                                disabled={assignableEntries.length === 0 || isAssigning}
                                                            >
                                                                <option value="">
                                                                    {assignableEntries.length === 0
                                                                        ? __("No synced roster entries available", "context-alt-text")
                                                                        : __("Select roster entry", "context-alt-text")}
                                                                </option>
                                                                {assignableEntries.map((entryOption) => (
                                                                    <option key={entryOption.remoteId ?? ""} value={entryOption.remoteId ?? ""}>
                                                                        {entryOption.label} ({entryOption.type})
                                                                    </option>
                                                                ))}
                                                            </select>
                                                            <button
                                                                type="button"
                                                                className="cat-button cat-button--primary"
                                                                onClick={() => {
                                                                    void handleAssign(record, attachment, suggestedRemoteId);
                                                                }}
                                                                disabled={assignableEntries.length === 0 || !selectedRemoteId || isAssigning}
                                                            >
                                                                {isAssigning
                                                                    ? __("Assigning…", "context-alt-text")
                                                                    : __("Assign existing entry", "context-alt-text")}
                                                            </button>
                                                            <button
                                                                type="button"
                                                                className="cat-button cat-button--subtle"
                                                                onClick={() => onCreate(record, attachment)}
                                                            >
                                                                {__("Create new entry", "context-alt-text")}
                                                            </button>
                                                        </div>
                                                    </li>
                                                );
                                            })}
                                        </ul>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </>
            )}
        </section>
    );
};

export const RosterRoute = ({ bootstrap, config }: RosterRouteProps): React.JSX.Element => {
    const [searchInput, setSearchInput] = React.useState<string>("");
    const [search, setSearch] = React.useState<string | null>(null);
    const [page, setPage] = React.useState<number>(1);
    const [perPage, setPerPage] = React.useState<number>(20);
    const [editing, setEditing] = React.useState<RosterEntry | null>(null);
    const [isSubmitting, setIsSubmitting] = React.useState<boolean>(false);
    const [statusFilter, setStatusFilter] = React.useState<RosterFilters["status"]>(null);
    const [draftValues, setDraftValues] = React.useState<{ label?: string; type?: string } | null>(null);
    const [observationPrompt, setObservationPrompt] = React.useState<ObservationPromptState | null>(null);
    const location = useLocation();
    const navigate = useNavigate();
    const deepLinkRef = React.useRef<{ remoteId?: string | null; draftSignature?: string | null }>({});
    const previousStatusRef = React.useRef<RosterFilters["status"]>(null);

    React.useEffect(() => {
        const timer = window.setTimeout(() => {
            const value = searchInput.trim();
            setSearch(value.length > 0 ? value : null);
            setPage(1);
        }, SEARCH_DEBOUNCE_MS);

        return () => window.clearTimeout(timer);
    }, [searchInput]);

    React.useEffect(() => {
        if (previousStatusRef.current === statusFilter) {
            return;
        }

        previousStatusRef.current = statusFilter ?? null;
        setPage(1);
    }, [statusFilter]);

    const filters = React.useMemo<RosterFilters>(() => {
        const base: RosterFilters = {
            search,
            page,
            perPage,
        };

        if (statusFilter) {
            base.status = statusFilter;
        }

        return base;
    }, [search, page, perPage, statusFilter]);

    const roster = useRoster({ initialData: bootstrap, config, filters });
    const {
        query,
        hasEndpoint,
        createEntry,
        updateEntry,
        deleteEntry,
        syncRoster,
        isSyncing,
    } = roster;

    const observationFilters = React.useMemo(
        () => ({
            status: "needs_review" as const,
            perPage: 10,
        }),
        [],
    );
    const observations = useRecognitionObservations({ config, filters: observationFilters });
    const observationResult = observations.query.data;
    const observationItems = React.useMemo(
        () => observationResult?.items ?? [],
        [observationResult?.items],
    );
    const observationSummary = observationResult?.summary ?? DEFAULT_OBSERVATION_SUMMARY;
    const observationsError = observations.query.error ?? null;
    const observationsLoading = observations.query.isFetching || observations.query.isLoading;
    const observationIndex = React.useMemo(() => {
        const entries = new Map<string, { record: RecognitionObservationRecord; attachment: RecognitionObservationAttachment }>();

        for (const attachment of observationItems) {
            if (!attachment || !Array.isArray(attachment.observations)) {
                continue;
            }

            for (const record of attachment.observations) {
                if (!record || typeof record !== "object") {
                    continue;
                }

                if (record.observationId) {
                    entries.set(record.observationId, { record, attachment });
                }
            }
        }

        return entries;
    }, [observationItems]);

    const data = query.data ?? {
        entries: bootstrap.entries,
        stats: bootstrap.stats,
        total: bootstrap.entries.length,
        page,
        perPage,
        totalPages: bootstrap.entries.length > 0 ? Math.ceil(bootstrap.entries.length / perPage) : 0,
        filters,
        syncState: {},
    };
    const entries = data.entries;
    const handleObservationSelect = React.useCallback(
        (
            record: RecognitionObservationRecord,
            attachment: RecognitionObservationAttachment,
        ) => {
            if (!record?.observationId) {
                return;
            }

            const params = buildObservationSearchParams(record, attachment.attachmentId ?? null);
            const nextPrompt: ObservationPromptState = {
                observationId: record.observationId,
                attachmentId: attachment.attachmentId ?? null,
                source: "recognition",
                remoteId: record.roster?.remoteId ?? null,
                label: record.label ?? null,
            };

            setObservationPrompt(nextPrompt);

            const nextDraft: RosterEditorDraft = {
                label: record.label ?? undefined,
                type: record.entityType ?? undefined,
                avatarUrl: attachment.context?.imageUrl ?? null,
                avatarId: null,
            };
            setDraftValues(nextDraft);

            if (record.roster?.remoteId) {
                const match = entries.find((entry) => entry.remoteId === record.roster?.remoteId) ?? null;
                setEditing(match);
            } else {
                const existing = entries.find((entry) => entry.label === nextDraft.label && entry.type === nextDraft.type) ?? null;
                if (existing) {
                    setEditing(existing);
                } else {
                    setEditing(null);
                }
            }

            const labelValue = nextDraft.label ?? "";
            if (labelValue) {
                setSearchInput((current) => (current === labelValue ? current : labelValue));
            }

            const nextSearch = params.toString();
            const nextUrl = nextSearch ? `${location.pathname}?${nextSearch}` : location.pathname;
            void navigate(nextUrl, { replace: true });
        },
        [entries, location.pathname, navigate],
    );

    const handleAssignToRoster = React.useCallback(
        async (
            record: RecognitionObservationRecord,
            attachment: RecognitionObservationAttachment,
            remoteId: string,
        ) => {
            if (!record.observationId || !attachment.attachmentId) {
                notifyError(__("Unable to resolve observation details.", "context-alt-text"), {
                    id: "cat-roster-observation-assign-error",
                });
                return;
            }

            const entry = entries.find((item) => item.remoteId === remoteId) ?? null;

            if (!entry) {
                notifyError(__("Select a roster entry with a remote ID to assign.", "context-alt-text"), {
                    id: "cat-roster-observation-assign-error",
                });
                return;
            }

            try {
                await updateEntry({
                    remoteId,
                    label: entry.label,
                    type: entry.type,
                    resolveObservation: {
                        attachmentId: attachment.attachmentId,
                        observationId: record.observationId,
                        status: "matched",
                        label: entry.label ?? record.label ?? null,
                        entityType: entry.type ?? record.entityType ?? null,
                    },
                });

                dispatchNotice(
                    "success",
                    sprintf(
                        /* translators: %s is a roster entry label. */
                        __("Observation matched to %s.", "context-alt-text"),
                        entry.label,
                    ),
                    { id: "cat-roster-observation-assign-success" },
                );

                if (observations.hasEndpoint) {
                    void observations.query.refetch();
                }

                setObservationPrompt({
                    observationId: record.observationId,
                    attachmentId: attachment.attachmentId,
                    source: "recognition",
                    remoteId,
                    label: entry.label ?? record.label ?? null,
                });

                setDraftValues(null);
                setEditing(entry);
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error);
                notifyError(message, { id: "cat-roster-observation-assign-error" });
            }
        },
        [entries, observations, updateEntry],
    );

    React.useEffect(() => {
        const params = new URLSearchParams(location.search ?? "");
        const filterParam = (params.get("filter") ?? "").toLowerCase();
        const remoteIdParam = params.get("remoteId");
        const modeParam = params.get("mode");
        const rawLabel = params.get("label");
        const rawType = params.get("type");
        const observationIdParam = params.get("observationId");
        const attachmentIdParam = params.get("attachmentId");
        const sourceParam = params.get("source");
        const labelValue = rawLabel ? rawLabel.trim() : "";
        const typeValue = rawType ? rawType.trim() : "";

        const normalizedAttachmentId = (() => {
            if (!attachmentIdParam) {
                return null;
            }

            const parsed = Number(attachmentIdParam);
            return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
        })();

        const normalizedSource = (() => {
            if (!sourceParam) {
                return null;
            }

            const trimmed = sourceParam.trim();
            return trimmed.length > 0 ? trimmed : null;
        })();

        const normalizedRemoteId = (() => {
            if (!remoteIdParam) {
                return null;
            }

            const trimmed = remoteIdParam.trim();
            return trimmed.length > 0 ? trimmed : null;
        })();

        const normalizedLabel = labelValue.length > 0 ? labelValue : null;

        const nextObservationPrompt: ObservationPromptState | null = observationIdParam
            ? {
                observationId: observationIdParam,
                attachmentId: normalizedAttachmentId,
                source: normalizedSource,
                remoteId: normalizedRemoteId,
                label: normalizedLabel,
            }
            : null;

        setObservationPrompt((current) => {
            if (!current && !nextObservationPrompt) {
                return current;
            }

            if (
                current &&
                nextObservationPrompt &&
                current.observationId === nextObservationPrompt.observationId &&
                current.attachmentId === nextObservationPrompt.attachmentId &&
                current.source === nextObservationPrompt.source &&
                current.remoteId === nextObservationPrompt.remoteId &&
                current.label === nextObservationPrompt.label
            ) {
                return current;
            }

            return nextObservationPrompt;
        });

        const statusMap: Record<string, RosterFilters["status"]> = {
            pending: "LOCAL",
            local: "LOCAL",
            synced: "SYNCED",
            conflict: "CONFLICT",
            conflicts: "CONFLICT",
        };

        if (!normalizedRemoteId && deepLinkRef.current.remoteId) {
            deepLinkRef.current.remoteId = null;
        }

        if (!modeParam && deepLinkRef.current.draftSignature) {
            deepLinkRef.current.draftSignature = null;
        }

        if (filterParam) {
            const mapped = statusMap[filterParam];
            if (mapped && mapped !== statusFilter) {
                setStatusFilter(mapped);
            }
        } else if (statusFilter) {
            setStatusFilter(null);
        }

        if (normalizedRemoteId) {
            if (deepLinkRef.current.remoteId === normalizedRemoteId && editing?.remoteId === normalizedRemoteId) {
                return;
            }

            const match = entries.find((entry) => entry.remoteId === normalizedRemoteId);
            if (match) {
                setEditing(match);
                setDraftValues(null);
                deepLinkRef.current.remoteId = normalizedRemoteId;
            } else {
                setSearchInput((current) => (current === normalizedRemoteId ? current : normalizedRemoteId));
            }

            return;
        }

        if (modeParam === "create") {
            const signature = `${labelValue}|${typeValue}`;
            if (deepLinkRef.current.draftSignature === signature) {
                return;
            }

            deepLinkRef.current.draftSignature = signature;
            setEditing(null);
            const nextDraft = {
                label: labelValue !== "" ? labelValue : undefined,
                type: typeValue !== "" ? typeValue : undefined,
            };
            setDraftValues(nextDraft);

            if (labelValue) {
                setSearchInput((current) => (current === labelValue ? current : labelValue));
            }
        }
    }, [location.search, entries, editing?.remoteId, statusFilter]);

    React.useEffect(() => {
        const result = query.data;

        if (!result || query.isFetching) {
            return;
        }

        const resultFilters = result.filters ?? {};
        const requestedSearch = filters.search ?? null;
        const requestedStatus = filters.status ?? null;
        const resultSearch = resultFilters.search ?? null;
        const resultStatus = resultFilters.status ?? null;

        const filtersMatch = resultSearch === requestedSearch && resultStatus === requestedStatus;

        if (!filtersMatch) {
            return;
        }

        if (Number.isFinite(result.perPage) && result.perPage > 0 && result.perPage !== perPage) {
            setPerPage(result.perPage);
        }

        if (Number.isFinite(result.page) && result.page > 0 && result.page !== page) {
            setPage(result.page);
        }

        if (resultStatus !== statusFilter) {
            setStatusFilter(resultStatus);
        }
    }, [filters, page, perPage, query.data, query.isFetching, statusFilter]);

    React.useEffect(() => {
        if (!query.error) {
            return;
        }

        notifyError(query.error.message, { id: "cat-roster-error" });
    }, [query.error]);

    const handleDismissObservationPrompt = React.useCallback(() => {
        setObservationPrompt(null);
        const params = new URLSearchParams(location.search ?? "");
        params.delete("observationId");
        params.delete("attachmentId");
        params.delete("source");
        params.delete("mode");
        params.delete("label");
        params.delete("type");
        params.delete("remoteId");
        const nextSearch = params.toString();
        const nextUrl = nextSearch ? `${location.pathname}?${nextSearch}` : location.pathname;
        void navigate(nextUrl, { replace: true });
    }, [location.pathname, location.search, navigate]);

    const handleSubmit = async (values: RosterFormValues) => {
        try {
            setIsSubmitting(true);

            if (values.remoteId) {
                // Update existing entry
                const entry = await updateEntry(values);
                if (entry) {
                    dispatchNotice("success", __("Roster entry saved.", "context-alt-text"), {
                        id: "cat-roster-save",
                    });
                    setEditing(null);
                } else {
                    dispatchNotice("success", __("Roster entry processed.", "context-alt-text"), {
                        id: "cat-roster-save-generic",
                    });
                }
            } else {
                // Create new entry
                const result = await createEntry(values);
                const entry = result?.entry ?? null;
                const autoMatched = result?.autoMatched ?? [];

                if (entry) {
                    const matchCount = autoMatched.length;
                    if (matchCount > 0) {
                        dispatchNotice(
                            "success",
                            sprintf(
                                _n(
                                    "Roster entry created and %d observation auto-matched.",
                                    "Roster entry created and %d observations auto-matched.",
                                    matchCount,
                                    "context-alt-text"
                                ),
                                matchCount
                            ),
                            { id: "cat-roster-save" }
                        );
                    } else {
                        dispatchNotice("success", __("Roster entry saved.", "context-alt-text"), {
                            id: "cat-roster-save",
                        });
                    }
                    setEditing(null);
                } else {
                    dispatchNotice("success", __("Roster entry processed.", "context-alt-text"), {
                        id: "cat-roster-save-generic",
                    });
                }
            }

            if (observationPrompt) {
                handleDismissObservationPrompt();
            }

            setDraftValues(null);
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            notifyError(message, { id: "cat-roster-save-error" });
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleDelete = async (remoteId: string) => {
        if (!window.confirm(__("Are you sure you want to delete this roster entry?", "context-alt-text"))) {
            return;
        }

        try {
            setIsSubmitting(true);
            await deleteEntry(remoteId);
            dispatchNotice("success", __("Roster entry deleted.", "context-alt-text"), {
                id: "cat-roster-delete",
            });
            if (editing?.remoteId === remoteId) {
                setEditing(null);
                setDraftValues(null);
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            notifyError(message, { id: "cat-roster-delete-error" });
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleSync = async () => {
        try {
            await syncRoster();
            if (observations.hasEndpoint) {
                void observations.query.refetch();
            }
            dispatchNotice("success", __("Roster sync completed.", "context-alt-text"), {
                id: "cat-roster-sync",
            });
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            notifyError(message, { id: "cat-roster-sync-error" });
        }
    };

    const handleEdit = (entry: RosterEntry) => {
        setDraftValues(null);
        setEditing(entry);
    };

    const handleCreateNew = () => {
        setDraftValues(null);
        setEditing(null);
    };

    const handleClearStatusFilter = React.useCallback(() => {
        setStatusFilter(null);
        const params = new URLSearchParams(location.search ?? "");

        if (!params.has("filter")) {
            return;
        }

        params.delete("filter");
        const nextSearch = params.toString();
        const nextUrl = nextSearch ? `${location.pathname}?${nextSearch}` : location.pathname;
        void navigate(nextUrl, { replace: true });
    }, [location.pathname, location.search, navigate]);

    const isLoading = query.isFetching || query.isLoading;
    const handlePageChange = (nextPage: number) => {
        setPage((current) => {
            if (nextPage <= 1) {
                return 1;
            }

            if (data.totalPages > 0 && nextPage > data.totalPages) {
                return data.totalPages;
            }

            if (!Number.isFinite(nextPage)) {
                return current;
            }

            return nextPage;
        });
    };

    const handlePerPageChange = (value: number) => {
        setPerPage((current) => {
            if (current === value) {
                return current;
            }

            setPage(1);
            return value;
        });
    };

    return (
        <div className="cat-roster">
            <header className="cat-roster__header">
                <div>
                    <h2>{__("Roster Manager", "context-alt-text")}</h2>
                    <p>
                        {__(
                            "Manage labeled faces and entities synchronized with the recognition service.",
                            "context-alt-text",
                        )}
                    </p>
                </div>
                <div className="cat-roster__header-actions">
                    <button
                        type="button"
                        className="cat-button"
                        onClick={handleCreateNew}
                        disabled={isSubmitting}
                    >
                        {__("Add Entry", "context-alt-text")}
                    </button>
                    <button
                        type="button"
                        className="cat-button cat-button--primary"
                        onClick={() => {
                            void handleSync();
                        }}
                        disabled={!hasEndpoint || isSyncing}
                    >
                        {isSyncing
                            ? __("Syncing…", "context-alt-text")
                            : __("Sync from Remote", "context-alt-text")}
                    </button>
                </div>
            </header>

            <section className="cat-roster__summary">
                <RosterStats stats={data.stats} />
                <div className="cat-roster__search">
                    <label htmlFor="cat-roster-search" className="screen-reader-text">
                        {__("Search roster", "context-alt-text")}
                    </label>
                    <input
                        id="cat-roster-search"
                        type="search"
                        value={searchInput}
                        placeholder={__("Search by label or type", "context-alt-text")}
                        onChange={(event) => setSearchInput(event.target.value)}
                        className="cat-roster__search-input"
                    />
                    {isLoading && (
                        <span className="cat-roster__search-status" role="status" aria-live="polite">
                            {__("Searching…", "context-alt-text")}
                        </span>
                    )}
                </div>
                {statusFilter && (
                    <div className="cat-roster__filter" role="status" aria-live="polite">
                        <span>
                            {sprintf(
                                __("Filtered by status: %s", "context-alt-text"),
                                statusFilter === "LOCAL"
                                    ? __("Local", "context-alt-text")
                                    : statusFilter === "SYNCED"
                                        ? __("Synced", "context-alt-text")
                                        : __("Conflict", "context-alt-text"),
                            )}
                        </span>
                        <button
                            type="button"
                            className="cat-button cat-button--link"
                            onClick={handleClearStatusFilter}
                            disabled={isLoading}
                        >
                            {__("Clear", "context-alt-text")}
                        </button>
                    </div>
                )}
            </section>

            {!hasEndpoint && (
                <p className="cat-roster__warning" role="alert">
                    {__(
                        "Roster endpoints are unavailable. Confirm REST routes are registered and you have required permissions.",
                        "context-alt-text",
                    )}
                </p>
            )}

            <RosterObservationsPanel
                attachments={observationItems}
                summary={observationSummary}
                isLoading={observationsLoading}
                error={observationsError}
                hasEndpoint={observations.hasEndpoint}
                entries={entries}
                onCreate={handleObservationSelect}
                onAssign={handleAssignToRoster}
                onRefresh={async () => {
                    if (!observations.hasEndpoint) {
                        return;
                    }

                    try {
                        // Trigger re-recognition for pending observations
                        const result = await observations.retryRecognition();

                        dispatchNotice("success", result.message, {
                            id: "cat-observations-retry",
                        });

                        // Refetch after a delay to allow recognition jobs to start
                        setTimeout(() => {
                            void observations.query.refetch();
                        }, 2000);
                    } catch (error) {
                        const message = error instanceof Error ? error.message : String(error);
                        notifyError(message, { id: "cat-observations-retry-error" });
                    }
                }}
            />

            <section className="cat-roster__layout">
                <RosterTable
                    entries={data.entries}
                    isLoading={isLoading}
                    onEdit={handleEdit}
                    onDelete={handleDelete}
                />
                <RosterEditor
                    entry={editing}
                    draftValues={draftValues}
                    observationPrompt={observationPrompt}
                    observationDetails={observationPrompt ? observationIndex.get(observationPrompt.observationId) : undefined}
                    onSubmit={handleSubmit}
                    submitting={isSubmitting}
                />
            </section>

            {observationPrompt && (
                <RosterObservationPrompt
                    prompt={observationPrompt}
                    details={observationIndex.get(observationPrompt.observationId)}
                    onDismiss={handleDismissObservationPrompt}
                />
            )}

            <RosterPagination
                page={data.page}
                totalPages={data.totalPages}
                total={data.total}
                perPage={data.perPage}
                onPageChange={handlePageChange}
                onPerPageChange={handlePerPageChange}
                disabled={isLoading}
            />
        </div>
    );
};

interface RosterStatsProps {
    stats: RosterData["stats"];
}

const RosterStats = ({ stats }: RosterStatsProps): React.JSX.Element => {
    return (
        <div className="cat-roster__stats" role="status" aria-live="polite">
            <dl>
                <div>
                    <dt>{__("Total", "context-alt-text")}</dt>
                    <dd>{stats.total}</dd>
                </div>
                <div>
                    <dt>{__("Synced", "context-alt-text")}</dt>
                    <dd>{stats.synced}</dd>
                </div>
                <div>
                    <dt>{__("Local", "context-alt-text")}</dt>
                    <dd>{stats.local}</dd>
                </div>
                <div>
                    <dt>{__("Conflicts", "context-alt-text")}</dt>
                    <dd>{stats.conflicts}</dd>
                </div>
            </dl>
            <p className="cat-roster__stats-sync">
                {stats.lastSyncHuman
                    ? sprintf(
                        __("Last synced %s ago.", "context-alt-text"),
                        stats.lastSyncHuman,
                    )
                    : __("Roster has not been synced yet.", "context-alt-text")}
            </p>
        </div>
    );
};

interface RosterObservationsPanelProps {
    attachments: RecognitionObservationAttachment[];
    summary: RecognitionObservationSummary;
    isLoading: boolean;
    error: Error | null;
    hasEndpoint: boolean;
    entries: RosterEntry[];
    onCreate: (record: RecognitionObservationRecord, attachment: RecognitionObservationAttachment) => void;
    onAssign: (
        record: RecognitionObservationRecord,
        attachment: RecognitionObservationAttachment,
        remoteId: string,
    ) => Promise<void> | void;
    onRefresh: () => void | Promise<void>;
}

// Duplicate implementation removed below. Single source of truth defined above.
/* const RosterObservationsPanel = ({
    attachments,
    summary,
    isLoading,
    error,
    hasEndpoint,
    entries,
    onCreate,
    onAssign,
    onRefresh,
}: RosterObservationsPanelProps): React.JSX.Element => {
    const pendingCount = Math.max(0, summary.observations.needs_review);
    const attachmentCount = Math.max(0, summary.attachments);
    const assignableEntries = React.useMemo(
        () => entries.filter((entry) => entry.remoteId && entry.remoteId.trim() !== ""),
        [entries],
    );
    return (
        <section className="cat-roster__observations" aria-live="polite">
            {!hasEndpoint ? (
                <>
                    <h3>{__("Recognition observations", "context-alt-text")}</h3>
                    <p className="cat-roster__observations-status">
                        {__(
                            "Recognition observations are unavailable. Enable the recognition feature flag to manage detected faces.",
                            "context-alt-text",
                        )}
                    </p>
                </>
            ) : (
                <>
                    <header className="cat-roster__observations-header">
                        <div>
                            <h3>{__("Recognition observations awaiting review", "context-alt-text")}</h3>
                            <p>
                                {pendingCount > 0
                                    ? sprintf(
                                        _n(
                                            "%1$d face across %2$d attachment requires a roster assignment.",
                                            "%1$d faces across %2$d attachments require roster assignments.",
                                            pendingCount,
                                            "context-alt-text",
                                        ),
                                        pendingCount,
                                        attachmentCount,
                                    )
                                    : __("Faces detected by recognition will appear here when they require review.", "context-alt-text")}
                            </p>
                        </div>
                        <div className="cat-roster__observations-actions">
                            <button
                                type="button"
                                className="cat-button cat-button--subtle"
                                onClick={() => void onRefresh()}
                                disabled={isLoading}
                            >
                                {isLoading ? __("Re-running…", "context-alt-text") : __("Re-run recognition", "context-alt-text")}
                            </button>
                        </div>
                    </header>

                    {error && (
                        <div className="cat-alert cat-alert--error" role="alert">
                            <span>{error.message}</span>
                        </div>
                    )}

                    {isLoading && pendingAttachments.length === 0 ? (
                        <p className="cat-roster__observations-status">{__("Loading observations…", "context-alt-text")}</p>
                    ) : null}

                    {!isLoading && pendingAttachments.length === 0 ? (
                        <p className="cat-roster__observations-status">
                            {__("No recognition observations require review right now.", "context-alt-text")}
                        </p>
                    ) : null}

                    {pendingAttachments.length > 0 && (
                        <ul className="cat-roster__observations-list">
                            {pendingAttachments.map(({ attachment, pending }) => {
                                const attachmentId = attachment.attachmentId;
                                const displayName = attachment.context?.filename
                                    ?? (attachmentId
                                        ? sprintf(
                                            // translators: %d is an attachment identifier.
                                            __("Attachment %d", "context-alt-text"),
                                            attachmentId,
                                        )
                                        : __("Media item", "context-alt-text"));
                                const unresolved = pending.length;

                                return (
                                    <li key={`${attachmentId ?? "unknown"}-${attachment.jobId ?? "job"}`} className="cat-roster__observations-item">
                                        <div className="cat-roster__observations-attachment">
                                            <div>
                                                <strong>{displayName}</strong>
                                                {attachment.context?.imageUrl && (
                                                    <a
                                                        href={attachment.context.imageUrl}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className="cat-roster__observations-link"
                                                    >
                                                        {__("Open", "context-alt-text")}
                                                    </a>
                                                )}
                                            </div>
                                            <span className="cat-roster__observations-count">
                                                {sprintf(
                                                    _n(
                                                        "%d face needs review",
                                                        "%d faces need review",
                                                        unresolved,
                                                        "context-alt-text",
                                                    ),
                                                    unresolved,
                                                )}
                                            </span>
                                        </div>
                                        <ul className="cat-roster__observations-faces">
                                            {pending.map((record) => {
                                                const displayLabel = record.label || record.entityType || __("Observation", "context-alt-text");
                                                const topCandidate = getTopCandidate(record);
                                                const rosterMatch = resolveSuggestedMatchLabel(record, assignableEntryLookup, topCandidate);
                                                const rosterConfidenceValue = getRosterConfidenceValue(record, topCandidate);
                                                const confidenceDisplay = formatPercentage(rosterConfidenceValue);
                                                const suggestedRemoteId = resolveSuggestedRemoteId(record, assignableEntryLookup, topCandidate);
                                                const selectedRemoteId = getSelectedRemoteId(record, selection, suggestedRemoteId);
                                                const isAssigning = assigningId === (record.observationId ?? null);

                                                return (
                                                    <li key={record.observationId} className="cat-roster__observations-face">
                                                        <ObservationPreview record={record} attachment={attachment} />
                                                        <div className="cat-roster__observations-face-details">
                                                            <span className="cat-roster__observations-label">{displayLabel}</span>
                                                            {rosterMatch ? (
                                                                <span className="cat-roster__observations-meta">
                                                                    {sprintf(
                                                                        __("Suggested match: %s", "context-alt-text"),
                                                                        rosterMatch,
                                                                    )}
                                                                </span>
                                                            ) : null}
                                                            {confidenceDisplay && (
                                                                <span className="cat-roster__observations-meta">
                                                                    {sprintf(
                                                                        __("Match confidence %s", "context-alt-text"),
                                                                        confidenceDisplay,
                                                                    )}
                                                                </span>
                                                            )}
                                                        </div>
                                                        <div className="cat-roster__observations-face-actions">
                                                            <label className="screen-reader-text" htmlFor={`cat-roster-observation-${record.observationId}-select`}>
                                                                {__("Select roster entry", "context-alt-text")}
                                                            </label>
                                                            <select
                                                                id={`cat-roster-observation-${record.observationId}-select`}
                                                                value={selectedRemoteId}
                                                                onChange={(event) =>
                                                                    setSelection((current) => ({
                                                                        ...current,
                                                                        [record.observationId ?? ""]: event.target.value,
                                                                    }))
                                                                }
                                                                disabled={assignableEntries.length === 0 || isAssigning}
                                                            >
                                                                <option value="">
                                                                    {assignableEntries.length === 0
                                                                        ? __("No synced roster entries available", "context-alt-text")
                                                                        : __("Select roster entry", "context-alt-text")}
                                                                </option>
                                                                {assignableEntries.map((entryOption) => (
                                                                    <option key={entryOption.remoteId ?? ""} value={entryOption.remoteId ?? ""}>
                                                                        {entryOption.label} ({entryOption.type})
                                                                    </option>
                                                                ))}
                                                            </select>
                                                            <button
                                                                type="button"
                                                                className="cat-button cat-button--primary"
                                                                onClick={() => {
                                                                    void handleAssign(record, attachment, suggestedRemoteId);
                                                                }}
                                                                disabled={assignableEntries.length === 0 || !selectedRemoteId || isAssigning}
                                                            >
                                                                {isAssigning
                                                                    ? __("Assigning…", "context-alt-text")
                                                                    : __("Assign existing entry", "context-alt-text")}
                                                            </button>
                                                            <button
                                                                type="button"
                                                                className="cat-button cat-button--subtle"
                                                                onClick={() => onCreate(record, attachment)}
                                                            >
                                                                {__("Create new entry", "context-alt-text")}
                                                            </button>
                                                        </div>
                                                    </li>
                                                );
                                            })}
                                        </ul>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </>
            )}
        </section>
    );
                                                            {sprintf(
                                                                __("Suggested match: %s", "context-alt-text"),
                                                                rosterMatch,
                                                            )}
                                                        </span>
                                                    ) : null}
                                                    {confidenceDisplay && (
                                                        <span className="cat-roster__observations-meta">
                                                            {sprintf(
                                                                __("Match confidence %s", "context-alt-text"),
                                                                confidenceDisplay,
                                                            )}
                                                        </span>
                                                    )}
                                                </div>
                                                <div className="cat-roster__observations-face-actions">
                                                    <label className="screen-reader-text" htmlFor={`cat-roster-observation-${record.observationId}-select`}>
                                                        {__("Select roster entry", "context-alt-text")}
                                                    </label>
                                                    <select
                                                        id={`cat-roster-observation-${record.observationId}-select`}
                                                        value={selectedRemoteId}
                                                        onChange={(event) =>
                                                            setSelection((current) => ({
                                                                ...current,
                                                                [record.observationId ?? ""]: event.target.value,
                                                            }))
                                                        }
                                                        disabled={assignableEntries.length === 0 || isAssigning}
                                                    >
                                                        <option value="">
                                                            {assignableEntries.length === 0
                                                                ? __("No synced roster entries available", "context-alt-text")
                                                                : __("Select roster entry", "context-alt-text")}
                                                        </option>
                                                        {assignableEntries.map((entryOption) => (
                                                            <option key={entryOption.remoteId ?? ""} value={entryOption.remoteId ?? ""}>
                                                                {entryOption.label} ({entryOption.type})
                                                            </option>
                                                        ))}
                                                    </select>
                                                    <button
                                                        type="button"
                                                        className="cat-button cat-button--primary"
                                                        onClick={() => {
                                                            void handleAssign(record, attachment, suggestedRemoteId);
                                                        }}
                                                        disabled={assignableEntries.length === 0 || !selectedRemoteId || isAssigning}
                                                    >
                                                        {isAssigning
                                                            ? __("Assigning…", "context-alt-text")
                                                            : __("Assign existing entry", "context-alt-text")}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        className="cat-button cat-button--subtle"
                                                        onClick={() => onCreate(record, attachment)}
                                                    >
                                                        {__("Create new entry", "context-alt-text")}
                                                    </button>
                                                </div>
                                            </li>
                                        );
                                    })}
                                </ul>
                            </li>
                        );
                    })}
                </ul>
            )}
        </section>
    );
}; */

interface RosterTableProps {
    entries: RosterEntry[];
    isLoading: boolean;
    onEdit: (entry: RosterEntry) => void;
    onDelete: (remoteId: string) => Promise<void> | void;
}

const RosterTable = ({ entries, isLoading, onEdit, onDelete }: RosterTableProps): React.JSX.Element => {
    if (entries.length === 0) {
        return (
            <div className="cat-roster__table cat-roster__table--empty">
                {isLoading ? (
                    <p>{__("Loading roster entries…", "context-alt-text")}</p>
                ) : (
                    <p>{__("No roster entries yet. Create one to get started.", "context-alt-text")}</p>
                )}
            </div>
        );
    }

    return (
        <div className="cat-roster__table" role="region" aria-live="polite">
            <table>
                <thead>
                    <tr>
                        <th scope="col">{__("Avatar", "context-alt-text")}</th>
                        <th scope="col">{__("Label", "context-alt-text")}</th>
                        <th scope="col">{__("Type", "context-alt-text")}</th>
                        <th scope="col">{__("Status", "context-alt-text")}</th>
                        <th scope="col">{__("Updated", "context-alt-text")}</th>
                        <th scope="col">{__("Images", "context-alt-text")}</th>
                        <th scope="col" className="screen-reader-text">
                            {__("Actions", "context-alt-text")}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {entries.map((entry) => (
                        <tr key={entry.remoteId ?? `${entry.label}-${entry.type}`}>
                            <td>
                                {entry.avatarUrl ? (
                                    <img
                                        src={entry.avatarUrl}
                                        alt={sprintf(
                                            __("Avatar for %s", "context-alt-text"),
                                            entry.label?.trim() ? entry.label : entry.remoteId ?? "—",
                                        )}
                                        className="cat-roster__avatar"
                                    />
                                ) : (
                                    <span className="cat-roster__avatar cat-roster__avatar--placeholder" aria-hidden>
                                        {entry.label ? entry.label.charAt(0).toUpperCase() : "?"}
                                    </span>
                                )}
                            </td>
                            <td>
                                <strong>{entry.label?.trim() ? entry.label : entry.remoteId ?? "—"}</strong>
                                <div className="cat-roster__meta">
                                    {entry.remoteId ? (
                                        <span>{entry.remoteId}</span>
                                    ) : (
                                        <span>{__("Local draft", "context-alt-text")}</span>
                                    )}
                                </div>
                            </td>
                            <td>{entry.type?.trim() ? entry.type : "—"}</td>
                            <td>
                                <StatusBadge status={entry.status} />
                            </td>
                            <td>{entry.updatedAt ? new Date(entry.updatedAt).toLocaleString() : "—"}</td>
                            <td>
                                {sprintf(
                                    _n("%d image", "%d images", entry.referenceImageCount, "context-alt-text"),
                                    entry.referenceImageCount,
                                )}
                            </td>
                            <td className="cat-roster__actions">
                                <button type="button" className="cat-button cat-button--link" onClick={() => onEdit(entry)}>
                                    {__("Edit", "context-alt-text")}
                                </button>
                                {entry.remoteId && (
                                    <button
                                        type="button"
                                        className="cat-button cat-button--link cat-button--danger"
                                        onClick={() => {
                                            void onDelete(entry.remoteId!);
                                        }}
                                    >
                                        {__("Delete", "context-alt-text")}
                                    </button>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};

interface RosterEditorDraft {
    label?: string;
    type?: string;
    avatarUrl?: string | null;
    avatarId?: number | null;
}

interface RosterEditorProps {
    entry: RosterEntry | null;
    draftValues: RosterEditorDraft | null;
    observationPrompt: ObservationPromptState | null;
    observationDetails?: { record: RecognitionObservationRecord; attachment: RecognitionObservationAttachment } | null;
    onSubmit: (values: RosterFormValues) => Promise<void>;
    submitting: boolean;
}

const RosterEditor = ({
    entry,
    draftValues,
    observationPrompt,
    observationDetails = null,
    onSubmit,
    submitting,
}: RosterEditorProps): React.JSX.Element => {
    const observationRecord = observationDetails?.record ?? null;
    const observationAttachment = observationDetails?.attachment ?? null;

    const initialLabel = entry?.label ?? draftValues?.label ?? observationRecord?.label ?? "";
    const initialType = entry?.type ?? draftValues?.type ?? observationRecord?.entityType ?? "";
    const initialAvatarUrl = entry?.avatarUrl ?? draftValues?.avatarUrl ?? observationAttachment?.context?.imageUrl ?? "";
    const initialAvatarId = entry?.avatarId ?? draftValues?.avatarId ?? null;

    const [label, setLabel] = React.useState<string>(initialLabel);
    const [type, setType] = React.useState<string>(initialType);
    const [avatarUrl, setAvatarUrl] = React.useState<string>(initialAvatarUrl);
    const [avatarId, setAvatarId] = React.useState<number | null>(initialAvatarId);
    const topCandidate = observationRecord ? getTopCandidate(observationRecord) : null;

    React.useEffect(() => {
        const nextLabel = entry?.label ?? draftValues?.label ?? observationRecord?.label ?? "";
        const nextType = entry?.type ?? draftValues?.type ?? observationRecord?.entityType ?? "";
        const nextAvatarUrl = entry?.avatarUrl ?? draftValues?.avatarUrl ?? observationAttachment?.context?.imageUrl ?? "";
        const nextAvatarId = entry?.avatarId ?? draftValues?.avatarId ?? null;

        setLabel(nextLabel);
        setType(nextType);
        setAvatarUrl(nextAvatarUrl);
        setAvatarId(nextAvatarId);
    }, [
        entry?.remoteId,
        entry?.label,
        entry?.type,
        entry?.avatarUrl,
        entry?.avatarId,
        draftValues?.label,
        draftValues?.type,
        draftValues?.avatarUrl,
        draftValues?.avatarId,
        observationRecord?.label,
        observationRecord?.entityType,
        observationAttachment?.context?.imageUrl,
    ]);

    const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const trimmedAvatarUrl = avatarUrl.trim();
        const normalizedAvatarId = trimmedAvatarUrl ? avatarId ?? null : avatarId ?? null;
        const trimmedLabel = label.trim();
        const trimmedType = type.trim();

        let resolveObservation: RosterFormValues["resolveObservation"] | undefined;
        let referenceImages: RosterFormValues["referenceImages"] | undefined;

        if (
            observationPrompt?.observationId &&
            (observationPrompt.attachmentId ?? 0) > 0
        ) {
            resolveObservation = {
                attachmentId: observationPrompt.attachmentId ?? 0,
                observationId: observationPrompt.observationId,
                status: "matched",
                label: trimmedLabel,
                entityType: trimmedType,
            };
        }

        if (observationRecord && observationAttachment) {
            const rosterConfidenceValue = getRosterConfidenceValue(observationRecord, topCandidate);
            const detectionConfidenceValue = getDetectionConfidenceValue(observationRecord);
            const referenceMetadata: Record<string, unknown> = {
                source: "recognition",
                area: observationRecord.area,
            };

            if (rosterConfidenceValue !== null) {
                referenceMetadata.confidence = rosterConfidenceValue;
            }

            if (detectionConfidenceValue !== null) {
                referenceMetadata.detectionConfidence = detectionConfidenceValue;
            }

            if (observationRecord.match) {
                const { similarity, threshold, confidence } = observationRecord.match;
                if (similarity) {
                    referenceMetadata.similarity = similarity;
                }
                if (threshold) {
                    referenceMetadata.threshold = threshold;
                }
                if (confidence) {
                    referenceMetadata.matchConfidence = confidence;
                } else if (rosterConfidenceValue !== null) {
                    referenceMetadata.matchConfidence = rosterConfidenceValue;
                }
            } else if (rosterConfidenceValue !== null) {
                referenceMetadata.matchConfidence = rosterConfidenceValue;
            }

            if (observationRecord.observationId) {
                referenceMetadata.observationId = observationRecord.observationId;
            }

            if (observationRecord.entityType) {
                referenceMetadata.entityType = observationRecord.entityType;
            }

            if (trimmedLabel) {
                referenceMetadata.label = trimmedLabel;
            }

            Object.keys(referenceMetadata).forEach((key) => {
                if (referenceMetadata[key] === undefined || referenceMetadata[key] === null) {
                    delete referenceMetadata[key];
                }
            });

            const boundingBox = observationRecord.boundingBox?.length ? observationRecord.boundingBox : null;

            referenceImages = [
                {
                    attachmentId: observationAttachment.attachmentId ?? null,
                    imageUrl: observationAttachment.context?.imageUrl ?? null,
                    observationId: observationRecord.observationId ?? null,
                    boundingBox,
                    metadata: referenceMetadata,
                },
            ];
        }

        void onSubmit({
            remoteId: entry?.remoteId ?? null,
            label: trimmedLabel,
            type: trimmedType,
            avatarUrl: trimmedAvatarUrl ? trimmedAvatarUrl : null,
            avatarId: normalizedAvatarId,
            ...(resolveObservation ? { resolveObservation } : {}),
            ...(referenceImages ? { referenceImages } : {}),
        });
    };

    const mode = entry?.remoteId ? __("Edit Entry", "context-alt-text") : __("Add Entry", "context-alt-text");
    const status: RosterEntry["status"] = entry?.status ?? "LOCAL";
    const remoteIdDisplay = entry?.remoteId ?? __("Not yet synced", "context-alt-text");
    const updatedDisplay = entry?.updatedAt
        ? new Date(entry.updatedAt).toLocaleString()
        : __("Pending first sync", "context-alt-text");
    const fallbackLabelValue =
        label.trim() !== ""
            ? label
            : draftValues?.label && draftValues.label.trim() !== ""
                ? draftValues.label
                : entry?.label ?? observationRecord?.label ?? "";
    const matchConfidenceValue = observationRecord ? getRosterConfidenceValue(observationRecord, topCandidate) : null;
    const confidenceDisplay = formatPercentage(matchConfidenceValue);
    const similarityDisplay = observationRecord?.match ? formatPercentage(observationRecord.match.similarity) : null;
    const thresholdDisplay = observationRecord?.match ? formatPercentage(observationRecord.match.threshold) : null;
    const attachmentLabel = observationAttachment?.context?.filename ?? null;

    return (
        <aside className="cat-roster__editor">
            <h3>{mode}</h3>

            <div className="cat-roster__editor-status" role="status" aria-live="polite">
                <StatusBadge status={status} />
                <dl>
                    <div>
                        <dt>{__("Remote ID", "context-alt-text")}</dt>
                        <dd>{remoteIdDisplay}</dd>
                    </div>
                    <div>
                        <dt>{__("Last updated", "context-alt-text")}</dt>
                        <dd>{updatedDisplay}</dd>
                    </div>
                </dl>
            </div>

            <form onSubmit={handleSubmit}>
                {observationPrompt && (
                    <div className="cat-roster__editor-context" role="status" aria-live="polite">
                        <strong>
                            {observationPrompt.remoteId
                                ? __("Resolve the linked observation by confirming this roster entry.", "context-alt-text")
                                : __("Saving this entry will resolve a recognition observation.", "context-alt-text")}
                        </strong>
                        <p>
                            {observationPrompt.remoteId
                                ? __("Review the details and save to continue embedding processing.", "context-alt-text")
                                : __("Complete the fields below and save to begin embedding generation for the flagged observation.", "context-alt-text")}
                        </p>
                        {observationRecord && (
                            <dl className="cat-roster__observation-details">
                                {attachmentLabel && (
                                    <div>
                                        <dt>{__("Attachment", "context-alt-text")}</dt>
                                        <dd>{attachmentLabel}</dd>
                                    </div>
                                )}
                                {observationAttachment?.attachmentId ? (
                                    <div>
                                        <dt>{__("Attachment ID", "context-alt-text")}</dt>
                                        <dd>{observationAttachment.attachmentId}</dd>
                                    </div>
                                ) : null}
                                {observationRecord.entityType && (
                                    <div>
                                        <dt>{__("Entity type", "context-alt-text")}</dt>
                                        <dd>{observationRecord.entityType}</dd>
                                    </div>
                                )}
                                {confidenceDisplay && (
                                    <div>
                                        <dt>{__("Match confidence", "context-alt-text")}</dt>
                                        <dd>{confidenceDisplay}</dd>
                                    </div>
                                )}
                                {similarityDisplay && (
                                    <div>
                                        <dt>{__("Match similarity", "context-alt-text")}</dt>
                                        <dd>{similarityDisplay}</dd>
                                    </div>
                                )}
                                {thresholdDisplay && (
                                    <div>
                                        <dt>{__("Match threshold", "context-alt-text")}</dt>
                                        <dd>{thresholdDisplay}</dd>
                                    </div>
                                )}
                            </dl>
                        )}
                    </div>
                )}
                <div className="cat-field">
                    <label htmlFor="cat-roster-label">{__("Label", "context-alt-text")}</label>
                    <input
                        id="cat-roster-label"
                        type="text"
                        required
                        value={label}
                        onChange={(event) => setLabel(event.target.value)}
                    />
                </div>
                <div className="cat-field">
                    <label htmlFor="cat-roster-type">{__("Type", "context-alt-text")}</label>
                    <input
                        id="cat-roster-type"
                        type="text"
                        required
                        value={type}
                        onChange={(event) => setType(event.target.value)}
                    />
                </div>

                <AvatarPicker
                    avatarUrl={avatarUrl}
                    avatarId={avatarId}
                    fallbackLabel={fallbackLabelValue}
                    onChange={({ avatarUrl: nextUrl, avatarId: nextId }) => {
                        setAvatarUrl(nextUrl);
                        setAvatarId(nextId);
                    }}
                    disabled={submitting}
                />

                <div className="cat-field">
                    <label htmlFor="cat-roster-avatar">{__("Avatar URL", "context-alt-text")}</label>
                    <input
                        id="cat-roster-avatar"
                        type="url"
                        value={avatarUrl}
                        placeholder="https://example.test/image.jpg"
                        onChange={(event) => {
                            setAvatarUrl(event.target.value);
                            setAvatarId(null);
                        }}
                    />
                    <p className="description">
                        {__(
                            "Optional image URL used as a reference thumbnail and seed for embeddings.",
                            "context-alt-text",
                        )}
                    </p>
                </div>
                <div className="cat-roster__editor-actions">
                    <button type="submit" className="cat-button cat-button--primary" disabled={submitting}>
                        {submitting ? __("Saving…", "context-alt-text") : __("Save", "context-alt-text")}
                    </button>
                </div>
            </form>
        </aside>
    );
};

interface RosterObservationPromptProps {
    prompt: ObservationPromptState;
    details?: { record: RecognitionObservationRecord; attachment: RecognitionObservationAttachment } | null;
    onDismiss: () => void;
}

interface ObservationPreviewProps {
    record: RecognitionObservationRecord;
    attachment: RecognitionObservationAttachment;
}

const ObservationPreview = ({ record, attachment }: ObservationPreviewProps): React.JSX.Element => {
    const [dimensions, setDimensions] = React.useState<{ width: number; height: number } | null>(null);
    const handleLoad = React.useCallback((event: React.SyntheticEvent<HTMLImageElement>) => {
        const target = event.currentTarget;
        setDimensions({
            width: target.naturalWidth,
            height: target.naturalHeight,
        });
    }, []);

    const highlightStyle = React.useMemo(() => {
        if (!dimensions || !record.boundingBox || record.boundingBox.length < 4) {
            return null;
        }

        const coords = record.boundingBox.slice(0, 4).map((value) => Number(value));
        if (coords.some((value) => !Number.isFinite(value))) {
            return null;
        }

        const [x1, y1, x2, y2] = coords as [number, number, number, number];
        const width = Math.max(0, x2 - x1);
        const height = Math.max(0, y2 - y1);

        if (!dimensions.width || !dimensions.height || width <= 0 || height <= 0) {
            return null;
        }

        return {
            left: `${(x1 / dimensions.width) * 100}%`,
            top: `${(y1 / dimensions.height) * 100}%`,
            width: `${(width / dimensions.width) * 100}%`,
            height: `${(height / dimensions.height) * 100}%`,
        };
    }, [dimensions, record.boundingBox]);

    const imageUrl = attachment.context?.imageUrl ?? null;
    const label = record.label || record.entityType || __("Observation", "context-alt-text");
    const altText = sprintf(
        /* translators: %s is the observation label. */
        __("%s preview", "context-alt-text"),
        label,
    );

    return (
        <div
            className="cat-roster__observations-thumb"
            style={
                dimensions
                    ? {
                        aspectRatio: `${dimensions.width} / ${dimensions.height}`,
                    }
                    : { aspectRatio: "1 / 1" }
            }
        >
            {imageUrl ? (
                <>
                    <img src={imageUrl} alt={altText} onLoad={handleLoad} />
                    {highlightStyle && <span className="cat-roster__observations-highlight" style={highlightStyle} />}
                </>
            ) : (
                <span className="cat-roster__observations-thumb-placeholder" aria-hidden="true">
                    {label.charAt(0).toUpperCase()}
                </span>
            )}
        </div>
    );
};

const RosterObservationPrompt = ({ prompt, details = null, onDismiss }: RosterObservationPromptProps): React.JSX.Element => {
    const sourceLabel = (() => {
        if (!prompt.source) {
            return __("Unknown", "context-alt-text");
        }

        if (prompt.source.toLowerCase() === "recognition") {
            return __("Recognition workbench", "context-alt-text");
        }

        return prompt.source;
    })();

    const detailItems: { label: string; value: string }[] = [
        { label: __("Observation ID", "context-alt-text"), value: prompt.observationId },
    ];

    if (prompt.attachmentId) {
        detailItems.push({
            label: __("Attachment ID", "context-alt-text"),
            value: String(prompt.attachmentId),
        });
    }

    if (prompt.label) {
        detailItems.push({
            label: __("Suggested label", "context-alt-text"),
            value: prompt.label,
        });
    }

    if (prompt.source) {
        detailItems.push({
            label: __("Source", "context-alt-text"),
            value: sourceLabel,
        });
    }

    if (details?.attachment?.context?.filename) {
        detailItems.push({
            label: __("Filename", "context-alt-text"),
            value: details.attachment.context.filename,
        });
    }

    const topCandidate = details?.record ? getTopCandidate(details.record) : null;
    const suggestedMatchLabel = details?.record
        ? details.record.roster?.displayName
        ?? details.record.roster?.name
        ?? topCandidate?.name
        ?? topCandidate?.remoteId
        ?? null
        : null;

    if (suggestedMatchLabel) {
        detailItems.push({
            label: __("Suggested match", "context-alt-text"),
            value: suggestedMatchLabel,
        });
    }
    const confidenceDisplay = details?.record ? formatPercentage(getRosterConfidenceValue(details.record, topCandidate)) : null;

    if (confidenceDisplay) {
        detailItems.push({
            label: __("Match confidence", "context-alt-text"),
            value: confidenceDisplay,
        });
    }

    const similarityDisplay = details?.record?.match ? formatPercentage(details.record.match.similarity) : null;

    if (similarityDisplay) {
        detailItems.push({
            label: __("Match similarity", "context-alt-text"),
            value: similarityDisplay,
        });
    }

    const thresholdDisplay = details?.record?.match ? formatPercentage(details.record.match.threshold) : null;

    if (thresholdDisplay) {
        detailItems.push({
            label: __("Match threshold", "context-alt-text"),
            value: thresholdDisplay,
        });
    }

    const message = prompt.remoteId
        ? __("This observation is linked to an existing roster entry. Review and save to continue embedding processing.", "context-alt-text")
        : __("Create or update the roster entry to kick off embedding generation for this observation.", "context-alt-text");

    return (
        <aside className="cat-roster__observation-callout" role="status" aria-live="polite">
            <div>
                <h3>{__("Observation requires roster review", "context-alt-text")}</h3>
                <p>{message}</p>
            </div>
            {detailItems.length > 0 && (
                <dl className="cat-roster__observation-details">
                    {detailItems.map((item) => (
                        <div key={`${item.label}-${item.value}`}>
                            <dt>{item.label}</dt>
                            <dd>{item.value}</dd>
                        </div>
                    ))}
                </dl>
            )}
            <div className="cat-roster__observation-actions">
                <button type="button" className="cat-button cat-button--link" onClick={onDismiss}>
                    {__("Dismiss prompt", "context-alt-text")}
                </button>
            </div>
        </aside>
    );
};

interface AvatarPickerProps {
    avatarUrl: string;
    avatarId: number | null;
    fallbackLabel: string;
    onChange: (selection: { avatarUrl: string; avatarId: number | null }) => void;
    disabled: boolean;
}

const AvatarPicker = ({ avatarUrl, avatarId, fallbackLabel, onChange, disabled }: AvatarPickerProps): React.JSX.Element => {
    const frameRef = React.useRef<MediaFrame | null>(null);

    const openMediaModal = React.useCallback(() => {
        if (disabled) {
            return;
        }

        const mediaFactory = getWpMedia();

        if (!mediaFactory) {
            notifyError(
                __("Media library is unavailable. Ensure WordPress media scripts are enqueued.", "context-alt-text"),
                { id: "cat-roster-media-unavailable" },
            );
            return;
        }

        frameRef.current ??= mediaFactory({
            title: __("Select roster avatar", "context-alt-text"),
            button: { text: __("Use image", "context-alt-text") },
            library: { type: "image" },
            multiple: false,
        });

        const frame = frameRef.current;
        if (!frame) {
            return;
        }

        const onSelect = () => {
            const selection = frame.state()?.get("selection") as {
                first?: () => { toJSON?: () => Record<string, unknown> };
            } | undefined;

            const selected = selection?.first?.();
            const attachment = selected && typeof selected.toJSON === "function"
                ? selected.toJSON()
                : selected;

            if (!isRecord(attachment)) {
                return;
            }

            const getString = (candidate: unknown): string | null =>
                typeof candidate === "string" && candidate.trim() !== "" ? candidate : null;

            const getSizeUrl = (sizes: unknown): string | null => {
                if (!sizes || typeof sizes !== "object") {
                    return null;
                }

                const map = sizes as Record<string, unknown>;

                for (const key of ["medium", "medium_large", "large", "full", "thumbnail"]) {
                    const sizeCandidate = map[key];
                    if (!sizeCandidate || typeof sizeCandidate !== "object") {
                        continue;
                    }

                    const url = getString((sizeCandidate as Record<string, unknown>).url);
                    if (url) {
                        return url;
                    }
                }

                return null;
            };

            const resolvedUrl =
                getSizeUrl((attachment as { sizes?: unknown }).sizes)
                ?? getString((attachment as { url?: unknown }).url)
                ?? getString((attachment as { source_url?: unknown }).source_url);

            const rawId = (attachment as { id?: unknown }).id;
            const parsedId = typeof rawId === "number"
                ? rawId
                : typeof rawId === "string"
                    ? Number(rawId)
                    : NaN;

            if (!resolvedUrl) {
                notifyError(
                    __("Selected image is missing a URL.", "context-alt-text"),
                    { id: "cat-roster-media-missing-url" },
                );
                return;
            }

            onChange({
                avatarUrl: resolvedUrl,
                avatarId: Number.isFinite(parsedId) && parsedId > 0 ? parsedId : null,
            });
        };

        frame.off?.("select");
        frame.on("select", onSelect);
        frame.open();
    }, [disabled, onChange]);

    const handleClear = React.useCallback(() => {
        if (disabled) {
            return;
        }

        onChange({ avatarUrl: "", avatarId: null });
    }, [disabled, onChange]);

    const fallbackInitial = (() => {
        const first = fallbackLabel.trim().charAt(0).toUpperCase();
        return first !== "" ? first : "?";
    })();

    return (
        <div className="cat-roster__avatar-field">
            <span className="cat-roster__avatar-label">{__("Avatar", "context-alt-text")}</span>
            <div className="cat-roster__avatar-selector">
                {avatarUrl ? (
                    <img
                        src={avatarUrl}
                        alt={__("Selected avatar preview", "context-alt-text")}
                        className="cat-roster__avatar cat-roster__avatar--preview"
                    />
                ) : (
                    <span className="cat-roster__avatar cat-roster__avatar--placeholder cat-roster__avatar--preview" aria-hidden>
                        {fallbackInitial}
                    </span>
                )}
                <div className="cat-roster__avatar-actions">
                    <button
                        type="button"
                        className="cat-button cat-button--subtle"
                        onClick={openMediaModal}
                        disabled={disabled}
                    >
                        {avatarUrl
                            ? __("Replace image", "context-alt-text")
                            : __("Select image", "context-alt-text")}
                    </button>
                    {avatarUrl && (
                        <button
                            type="button"
                            className="cat-button cat-button--link"
                            onClick={handleClear}
                            disabled={disabled}
                        >
                            {__("Remove", "context-alt-text")}
                        </button>
                    )}
                    {avatarId && (
                        <span className="cat-roster__avatar-meta">
                            {sprintf(__("Attachment ID: %d", "context-alt-text"), avatarId)}
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
};

interface StatusBadgeProps {
    status: RosterEntry["status"];
}

const StatusBadge = ({ status }: StatusBadgeProps): React.JSX.Element => (
    <span className={`cat-roster__badge cat-roster__badge--${status.toLowerCase()}`}>
        {status === "SYNCED"
            ? __("Synced", "context-alt-text")
            : status === "CONFLICT"
                ? __("Conflict", "context-alt-text")
                : __("Local", "context-alt-text")}
    </span>
);

interface RosterPaginationProps {
    page: number;
    totalPages: number;
    total: number;
    perPage: number;
    onPageChange: (page: number) => void;
    onPerPageChange: (perPage: number) => void;
    disabled: boolean;
}

const RosterPagination = ({
    page,
    totalPages,
    total,
    perPage,
    onPageChange,
    onPerPageChange,
    disabled,
}: RosterPaginationProps): React.JSX.Element => {
    if (totalPages <= 1 && total <= perPage) {
        return <div className="cat-roster__pagination" aria-live="polite" />;
    }

    const canPrev = page > 1;
    const canNext = totalPages === 0 ? true : page < totalPages;

    return (
        <div className="cat-roster__pagination" aria-live="polite">
            <div className="cat-roster__pagination-controls">
                <button
                    type="button"
                    className="cat-button"
                    onClick={() => onPageChange(page - 1)}
                    disabled={disabled || !canPrev}
                >
                    {__("Previous", "context-alt-text")}
                </button>
                <span>
                    {sprintf(
                        __("Page %1$d of %2$d", "context-alt-text"),
                        page,
                        totalPages === 0 ? 1 : totalPages,
                    )}
                </span>
                <button
                    type="button"
                    className="cat-button"
                    onClick={() => onPageChange(page + 1)}
                    disabled={disabled || !canNext}
                >
                    {__("Next", "context-alt-text")}
                </button>
            </div>
            <div className="cat-roster__pagination-meta">
                <label htmlFor="cat-roster-per-page">
                    {__("Rows per page", "context-alt-text")}
                </label>
                <select
                    id="cat-roster-per-page"
                    value={perPage}
                    onChange={(event) => onPerPageChange(Number(event.target.value))}
                    disabled={disabled}
                >
                    {[10, 20, 50].map((value) => (
                        <option key={value} value={value}>
                            {value}
                        </option>
                    ))}
                </select>
                <span>
                    {sprintf(
                        _n("%d entry", "%d entries", total, "context-alt-text"),
                        total,
                    )}
                </span>
            </div>
        </div>
    );
};
