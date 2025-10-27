import React from "react";
import { __ } from "@wordpress/i18n";

import { ClusterCard } from "./ClusterCard";
import { useUnknownClusters } from "@/hooks/useUnknownClusters";
import type { FaceDragPayload } from "@/components/workbench/dragTypes";

export interface UnknownPeoplePanelProps {
    onSelectCluster?: (clusterId: string) => void;
    selectedClusterId?: string | null;
    onMoveFaces?: (payload: { targetClusterId: string; sourceClusterId: string; faceIds: string[] }) => void;
}

export const UnknownPeoplePanel = ({
    onSelectCluster,
    selectedClusterId = null,
    onMoveFaces,
}: UnknownPeoplePanelProps): React.JSX.Element => {
    const { clusters, isLoading, error, total } = useUnknownClusters({ perPage: 50 });
    const [activeDropClusterId, setActiveDropClusterId] = React.useState<string | null>(null);

    const handleDropFaces = React.useCallback(
        (clusterId: string, payload: FaceDragPayload) => {
            setActiveDropClusterId(null);

            if (payload.clusterId === clusterId) {
                return;
            }

            onSelectCluster?.(clusterId);
            onMoveFaces?.({
                targetClusterId: clusterId,
                sourceClusterId: payload.clusterId,
                faceIds: payload.faceIds,
            });
        },
        [onMoveFaces, onSelectCluster],
    );

    const handleDragEnter = React.useCallback((clusterId: string) => {
        setActiveDropClusterId(clusterId);
    }, []);

    const handleDragLeave = React.useCallback((clusterId: string) => {
        setActiveDropClusterId((current) => (current === clusterId ? null : current));
    }, []);

    return (
        <section className="cat-unknown-people-panel" aria-labelledby="cat-unknown-people-heading">
            <header className="cat-unknown-people-panel__header">
                <h2 id="cat-unknown-people-heading">{__("Unknown People", "context-alt-text")}</h2>
                <p>
                    {total > 0
                        ? __(
                              `Review ${total} detected face${total === 1 ? "" : "s"} grouped by similarity to confirm who they are.`,
                              "context-alt-text",
                          )
                        : __(
                              "Review detected faces grouped by similarity to confirm who they are.",
                              "context-alt-text",
                          )}
                </p>
            </header>

            {isLoading && (
                <p className="cat-unknown-people-panel__status" role="status" aria-live="polite">
                    {__("Loading unknown people…", "context-alt-text")}
                </p>
            )}

            {!isLoading && error && (
                <p className="cat-unknown-people-panel__error" role="alert">
                    {__("Unable to load unknown people. Try again shortly.", "context-alt-text")}
                </p>
            )}

            {!isLoading && !error && clusters.length === 0 && (
                <p className="cat-unknown-people-panel__empty">
                    {__("No unknown people are waiting for review.", "context-alt-text")}
                </p>
            )}

            {!isLoading && !error && clusters.length > 0 && (
                <div className="cat-unknown-people-panel__grid">
                    {clusters.map((cluster) => (
                        <ClusterCard
                            key={cluster.id}
                            cluster={cluster}
                            onClick={onSelectCluster}
                            isSelected={selectedClusterId === cluster.id}
                            onDropFaces={onMoveFaces ? handleDropFaces : undefined}
                            onDragEnter={onMoveFaces ? handleDragEnter : undefined}
                            onDragLeave={onMoveFaces ? handleDragLeave : undefined}
                            isDropTarget={activeDropClusterId === cluster.id}
                        />
                    ))}
                </div>
            )}
        </section>
    );
};
