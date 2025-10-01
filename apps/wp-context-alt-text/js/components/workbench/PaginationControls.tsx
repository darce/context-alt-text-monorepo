import React from "react";

import { Button } from "@/components/ui/button";

export interface PaginationControlsProps {
    page: number;
    perPage: number;
    total: number;
    totalPages: number;
    isLoading?: boolean;
    onPageChange: (page: number) => void;
}

export const PaginationControls = ({
    page,
    perPage,
    total,
    totalPages,
    isLoading = false,
    onPageChange,
}: PaginationControlsProps): React.JSX.Element | null => {
    if (totalPages <= 1 && total <= perPage) {
        return null;
    }

    const safePage = Math.max(1, Math.min(page, Math.max(totalPages, 1)));
    const start = total === 0 ? 0 : (safePage - 1) * perPage + 1;
    const end = total === 0 ? 0 : Math.min(total, safePage * perPage);

    const handlePrevious = () => {
        if (safePage > 1) {
            onPageChange(safePage - 1);
        }
    };

    const handleNext = () => {
        if (totalPages === 0 || safePage < totalPages) {
            onPageChange(safePage + 1);
        }
    };

    return (
        <nav className="cat-pagination" aria-label="Workbench pagination">
            <p className="cat-pagination__status">
                {total === 0
                    ? "No media items found"
                    : `Showing ${start}-${end} of ${total}${isLoading ? " (updating...)" : ""}`}
            </p>
            <div className="cat-pagination__buttons">
                <Button
                    variant="subtle"
                    size="sm"
                    onClick={handlePrevious}
                    disabled={safePage <= 1 || isLoading}
                >
                    Previous
                </Button>
                <span className="cat-pagination__page" aria-live="polite">
                    Page {safePage}
                    {totalPages > 0 ? ` of ${totalPages}` : ""}
                </span>
                <Button
                    variant="subtle"
                    size="sm"
                    onClick={handleNext}
                    disabled={(totalPages > 0 && safePage >= totalPages) || total === 0 || isLoading}
                >
                    Next
                </Button>
            </div>
        </nav>
    );
};
