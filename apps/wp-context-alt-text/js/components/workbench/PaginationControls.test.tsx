import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PaginationControls } from "./PaginationControls";

describe("PaginationControls", () => {
    it("disables navigation when only a single page is available", () => {
        render(
            <PaginationControls
                page={1}
                perPage={20}
                total={12}
                totalPages={1}
                onPageChange={vi.fn()}
            />,
        );

        expect(screen.getByText(/Showing 1-12 of 12/i)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Previous/i })).toBeDisabled();
        expect(screen.getByRole("button", { name: /Next/i })).toBeDisabled();
        expect(screen.getByRole("spinbutton", { name: /Jump to page/i })).toHaveValue(1);
    });

    it("invokes callbacks when pagination changes within bounds", async () => {
        const onPageChange = vi.fn();
        const onPerPageChange = vi.fn();
        const user = userEvent.setup();

        render(
            <PaginationControls
                page={2}
                perPage={10}
                total={55}
                totalPages={6}
                onPageChange={onPageChange}
                onPerPageChange={onPerPageChange}
            />,
        );

        await user.click(screen.getByRole("button", { name: /Next/i }));
        await waitFor(() => expect(onPageChange).toHaveBeenNthCalledWith(1, 3));

        await user.click(screen.getByRole("button", { name: /Previous/i }));
        await waitFor(() => expect(onPageChange).toHaveBeenNthCalledWith(2, 1));

        const select = screen.getByLabelText(/Items per page/i);
        await user.selectOptions(select, "20");
        await waitFor(() => expect(onPerPageChange).toHaveBeenCalledWith(20));

        const input = screen.getByLabelText(/Jump to page/i);
        await user.clear(input);
        await user.type(input, "4");
        fireEvent.submit(input.closest("form") as HTMLFormElement);

        await waitFor(() => expect(onPageChange).toHaveBeenNthCalledWith(3, 4));
    });

    it("clamps navigation when attempting to go beyond limits", async () => {
        const onPageChange = vi.fn();
        const user = userEvent.setup();

        render(
            <PaginationControls
                page={1}
                perPage={25}
                total={50}
                totalPages={2}
                onPageChange={onPageChange}
            />,
        );

        const input = screen.getByLabelText(/Jump to page/i);

        await user.clear(input);
        await user.type(input, "99");
        fireEvent.submit(input.closest("form") as HTMLFormElement);

        await waitFor(() => expect(onPageChange).toHaveBeenCalledWith(2));
    });
});
