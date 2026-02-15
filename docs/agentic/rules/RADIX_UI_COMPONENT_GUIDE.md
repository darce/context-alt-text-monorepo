# Radix UI Component Guide

Prefer Radix UI primitives over custom implementations for consistent, accessible components.

---

## Table of Contents

1. [Installed Packages](#installed-packages)
2. [Available Components](#available-components)
3. [Adding New Primitives](#adding-new-primitives)
4. [Essential Patterns](#essential-patterns)
5. [Accessibility Checklist](#accessibility-checklist)
6. [Testing](#testing)

---

## Installed Packages

These are ready to use in `js/components/ui/`:

| Package                     | Wrapper        | Use For                                        |
| --------------------------- | -------------- | ---------------------------------------------- |
| `@radix-ui/react-tooltip`   | `Tooltip.tsx`  | Icon buttons, abbreviations, status indicators |
| `@radix-ui/react-progress`  | `Progress.tsx` | File uploads, long operations                  |
| `@radix-ui/react-separator` | -              | Visual dividers                                |
| `@radix-ui/react-slot`      | `Button.tsx`   | Composable buttons                             |

---

## Available Components

### Tooltip (installed)

```tsx
import {
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";

<TooltipProvider>
  <TooltipRoot>
    <TooltipTrigger asChild>
      <button className="acx-button acx-button--icon">
        <RefreshIcon />
        <span className="screen-reader-text">
          {__("Refresh", "alt-context")}
        </span>
      </button>
    </TooltipTrigger>
    <TooltipContent side="top">
      {__("Refresh the roster data", "alt-context")}
    </TooltipContent>
  </TooltipRoot>
</TooltipProvider>;
```

**Rules:**

- Always include screen reader text in the trigger
- Keep tooltip text to 1-2 sentences
- Wrap app root with `TooltipProvider` once

### Progress (installed)

```tsx
import { Progress } from "@/components/ui/progress";

<Progress value={progress} max={100} />;
```

### Separator (installed)

```tsx
import { Separator } from "@radix-ui/react-separator";

<Separator orientation="horizontal" className="acx-separator" />;
```

---

## Adding New Primitives

When you need a component not yet installed, follow this priority order:

### High Priority (install when needed)

| Use Case                  | Package                  | Size  |
| ------------------------- | ------------------------ | ----- |
| Dropdowns with 3+ options | `@radix-ui/react-select` | 35 kB |
| Modals/dialogs            | `@radix-ui/react-dialog` | 18 kB |
| Form validation           | `@radix-ui/react-form`   | 5 kB  |
| Form labels               | `@radix-ui/react-label`  | 2 kB  |

### Medium Priority

| Use Case             | Package                     | Size  |
| -------------------- | --------------------------- | ----- |
| View switching       | `@radix-ui/react-tabs`      | 6 kB  |
| Collapsible sections | `@radix-ui/react-accordion` | 9 kB  |
| Non-modal overlays   | `@radix-ui/react-popover`   | 15 kB |

### Low Priority

| Use Case              | Package                       | Size |
| --------------------- | ----------------------------- | ---- |
| Boolean toggles       | `@radix-ui/react-switch`      | 3 kB |
| 3-5 exclusive options | `@radix-ui/react-radio-group` | 8 kB |
| Multiple selection    | `@radix-ui/react-checkbox`    | 3 kB |
| Numeric ranges        | `@radix-ui/react-slider`      | 6 kB |

### Installation Steps

1. `npm install @radix-ui/react-{component}`
2. Create wrapper in `js/components/ui/{component}.tsx`
3. Apply BEM classes: `acx-{component}`, `acx-{component}--variant`
4. Add TypeScript types extending Radix props
5. Write behavior tests (not implementation tests)
6. Run axe-core accessibility audit

---

## Essential Patterns

### asChild Composition

Merge Radix behavior with your components:

```tsx
// Radix primitive renders as your Button
<Dialog.Trigger asChild>
  <Button variant="primary">{__("Open", "alt-context")}</Button>
</Dialog.Trigger>
```

### Controlled vs Uncontrolled

```tsx
// Uncontrolled (Radix manages state)
<Dialog.Root defaultOpen={false}>...</Dialog.Root>

// Controlled (you manage state)
<Dialog.Root open={isOpen} onOpenChange={setIsOpen}>...</Dialog.Root>
```

Use controlled when you need to:

- Coordinate with other state
- Validate before closing
- Prevent closing conditionally

### Styling with Data Attributes

Radix adds state attributes for CSS:

```scss
.acx-dialog-overlay[data-state="open"] {
  animation: fadeIn 200ms ease-out;
}

.acx-select-item[data-highlighted] {
  background-color: var(--color-primary-50);
}

.acx-select-item[data-disabled] {
  opacity: 0.5;
  cursor: not-allowed;
}
```

**Available attributes:**

- `data-state`: "open" | "closed"
- `data-disabled`: present when disabled
- `data-highlighted`: keyboard focus
- `data-invalid` / `data-valid`: form field state

---

## Accessibility Checklist

Every Radix component must have:

### 1. Labels

```tsx
// Visible label
<Label htmlFor="email">{__("Email", "alt-context")}</Label>
<input id="email" type="email" />

// Or aria-label for icon buttons
<button aria-label={__("Close", "alt-context")}>
  <CrossIcon />
</button>
```

### 2. Screen Reader Text

```tsx
<button className="acx-button acx-button--icon">
  <RefreshIcon />
  <span className="screen-reader-text">{__("Refresh", "alt-context")}</span>
</button>
```

### 3. Dialog Titles and Descriptions

```tsx
<Dialog.Content>
  <Dialog.Title>{__("Delete Item", "alt-context")}</Dialog.Title>
  <Dialog.Description>
    {__("This action cannot be undone.", "alt-context")}
  </Dialog.Description>
</Dialog.Content>
```

### 4. Keyboard Navigation

Test every component with:

- Tab / Shift+Tab
- Arrow keys
- Enter / Space
- Escape

### 5. Internationalization

All user-visible strings through WordPress i18n:

```tsx
import { __ } from "@wordpress/i18n";

<Label>{__("First Name", "alt-context")}</Label>;
```

---

## Testing

### Behavior Tests

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

test("dialog opens and closes", async () => {
  const user = userEvent.setup();

  render(
    <Dialog>
      <DialogTrigger>Open</DialogTrigger>
      <DialogContent>
        <DialogTitle>Title</DialogTitle>
        <DialogClose>Close</DialogClose>
      </DialogContent>
    </Dialog>,
  );

  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  await user.click(screen.getByText("Open"));
  expect(screen.getByRole("dialog")).toBeInTheDocument();

  await user.click(screen.getByText("Close"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
```

### Accessibility Tests

```tsx
import { axe } from "vitest-axe";

test("component has no accessibility violations", async () => {
  const { container } = render(<MyRadixComponent />);
  const results = await axe(container);
  expect(results).toHaveNoViolations();
});
```

---

## Resources

- [Radix UI Docs](https://www.radix-ui.com/primitives/docs/overview/introduction)
- [shadcn/ui](https://ui.shadcn.com/) - Production patterns built on Radix
