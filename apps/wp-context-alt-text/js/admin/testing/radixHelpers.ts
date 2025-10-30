import { screen, waitFor } from "@testing-library/react";
import { expect } from "vitest";
import type { UserEvent } from "@testing-library/user-event";

/**
 * Helper function to select an option from a Radix UI Select component in tests.
 *
 * Radix Select uses a button trigger and portal-based dropdown, which requires
 * a different interaction pattern than native <select> elements.
 *
 * @param user - UserEvent instance from userEvent.setup()
 * @param triggerLabel - Accessible label or name of the select trigger
 * @param optionText - Text content of the option to select
 *
 * @example
 * ```tsx
 * const user = userEvent.setup();
 * await selectRadixOption(user, /Items per page/i, "20");
 * ```
 */
export const selectRadixOption = async (
    user: UserEvent,
    triggerLabel: string | RegExp,
    optionText: string,
): Promise<void> => {
    // Find the trigger button (Radix Select uses role="combobox")
    const trigger = screen.getByRole("combobox", { name: triggerLabel });

    // Click to open the dropdown
    await user.click(trigger);

    // Wait for the dropdown to appear and find the option
    const option = await screen.findByRole("option", { name: optionText });

    // Click the option to select it
    await user.click(option);

    // Wait for the dropdown to close
    await waitFor(() => {
        expect(trigger).toHaveAttribute("aria-expanded", "false");
    });
};

/**
 * Helper function to check a Radix UI Checkbox component in tests.
 *
 * Radix Checkbox uses a button with role="checkbox" instead of native input.
 *
 * @param user - UserEvent instance from userEvent.setup()
 * @param checkboxLabel - Accessible label or name of the checkbox
 *
 * @example
 * ```tsx
 * const user = userEvent.setup();
 * await toggleRadixCheckbox(user, /Enable recognition/i);
 * ```
 */
export const toggleRadixCheckbox = async (user: UserEvent, checkboxLabel: string | RegExp): Promise<void> => {
    const checkbox = screen.getByRole("checkbox", { name: checkboxLabel });
    await user.click(checkbox);
};

/**
 * Helper function to get the current value of a Radix UI Select component.
 *
 * @param triggerLabel - Accessible label or name of the select trigger
 * @returns The text content of the currently selected value
 *
 * @example
 * ```tsx
 * const value = getRadixSelectValue(/Items per page/i);
 * expect(value).toBe("20");
 * ```
 */
export const getRadixSelectValue = (triggerLabel: string | RegExp): string => {
    const trigger = screen.getByRole("combobox", { name: triggerLabel });
    // Radix Select displays the value in a span with pointer-events: none
    const valueSpan = trigger.querySelector('[style*="pointer-events"]');
    return valueSpan?.textContent?.trim() ?? "";
};
