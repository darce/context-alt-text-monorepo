import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SearchBar } from "./SearchBar";

const StatefulSearchBar = ({
    initialValue = "",
    onSearch = vi.fn(),
    ...props
}: Partial<React.ComponentProps<typeof SearchBar>> & { initialValue?: string; onSearch?: (query: string) => void }) => {
    const [value, setValue] = React.useState(initialValue);

    const handleSearch = React.useCallback(
        (query: string) => {
            setValue(query);
            onSearch(query);
        },
        [onSearch],
    );

    return <SearchBar value={value} onSearch={handleSearch} {...props} />;
};

describe("SearchBar", () => {

    it("renders search input with placeholder", () => {
        render(<SearchBar value="" onSearch={vi.fn()} />);

        const input = screen.getByRole("searchbox", { name: /search media/i });
        expect(input).toBeInTheDocument();
        expect(input).toHaveAttribute("placeholder", "Search by filename or alt text...");
    });

    it("calls onSearch with updated input value", () => {
        const onSearch = vi.fn();

        render(<StatefulSearchBar onSearch={onSearch} />);

        const input = screen.getByRole("searchbox");

        fireEvent.change(input, { target: { value: "test query" } });

        expect(onSearch).toHaveBeenCalledWith("test query");
        expect(onSearch).toHaveBeenCalledTimes(1);
        expect((input as HTMLInputElement).value).toBe("test query");
    });

    it("supports controlled value prop", () => {
        const { rerender } = render(<SearchBar onSearch={vi.fn()} value="initial" />);

        const input = screen.getByRole("searchbox") as HTMLInputElement;
        expect(input.value).toBe("initial");

        rerender(<SearchBar onSearch={vi.fn()} value="updated" />);
        expect(input.value).toBe("updated");
    });

    it("shows clear button when input has value", () => {
        render(<StatefulSearchBar initialValue="test" />);

        // No clear button initially
        expect(screen.getByRole("button", { name: /clear search/i })).toBeInTheDocument();
    });

    it("clears input and calls onSearch with empty string when clear button clicked", () => {
        const onSearch = vi.fn();

        render(<StatefulSearchBar initialValue="test query" onSearch={onSearch} />);

        onSearch.mockClear();

        const input = screen.getByRole("searchbox") as HTMLInputElement;
        const clearButton = screen.getByRole("button", { name: /clear search/i });
        fireEvent.click(clearButton);

        expect(onSearch).toHaveBeenCalledWith("");
        expect(onSearch).toHaveBeenCalledTimes(1);
        expect(input.value).toBe("");
    });

    it("has accessible label", () => {
        render(<SearchBar value="" onSearch={vi.fn()} />);

        const input = screen.getByRole("searchbox");
        expect(input).toHaveAccessibleName(/search media/i);
    });

    it("renders loading spinner when isLoading is true", () => {
        render(<SearchBar value="" onSearch={vi.fn()} isLoading spinnerLabel="Searching" />);

        const spinner = screen.getByRole("status", { name: /searching/i });
        expect(spinner).toBeInTheDocument();
    });

    it("shows error message and retry button when error provided", () => {
        const onRetry = vi.fn();

        render(<SearchBar value="" onSearch={vi.fn()} error="Network error" onRetry={onRetry} />);

        expect(screen.getByRole("alert")).toHaveTextContent("Network error");

        const retryButton = screen.getByRole("button", { name: /retry search/i });
        fireEvent.click(retryButton);

        expect(onRetry).toHaveBeenCalledTimes(1);
    });

    it("announces status message for assistive technology", () => {
        render(<SearchBar value="" onSearch={vi.fn()} statusMessage="Showing 12 results" />);

        const liveRegion = screen.getByTestId("workbench-search-status");
        expect(liveRegion).toHaveAttribute("aria-live", "polite");
        expect(liveRegion).toHaveClass("screen-reader-text");
        expect(liveRegion).toHaveTextContent("Showing 12 results");
    });
});
