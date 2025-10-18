# Radix UI Component Development Guide

**Status**: MANDATORY REFERENCE for all new React component development  
**Last Updated**: October 18, 2025  
**Authoritative Source**: This guide must be consulted before implementing any new UI component

## Purpose

This guide provides instant access to Radix UI primitives for consistent, accessible component development. Reference this document BEFORE writing custom implementations of common UI patterns.

---

## Quick Decision Tree

```
Are you building a new component?
|
+-- Is it a form input? --> See "Form Components" section
|
+-- Is it a dropdown/menu? --> See "Overlay Components" section
|
+-- Is it a modal/dialog? --> See "Dialog Components" section
|
+-- Is it navigation? --> See "Navigation Components" section
|
+-- Does it need a tooltip? --> See "Feedback Components" section
|
+-- Is it a status indicator? --> See "Data Display Components" section
```

---

## Installed Radix UI Packages

**Current Installation** (from `package.json`):

```json
{
  "@radix-ui/react-progress": "^1.0.3",
  "@radix-ui/react-separator": "^1.1.7",
  "@radix-ui/react-slot": "^1.2.3",
  "@radix-ui/react-tooltip": "^1.1.3"
}
```

**Wrapper Components Available** (`js/components/ui/`):

- `Button.tsx` - Composable button using Slot primitive
- `Tooltip.tsx` - Accessible tooltips with arrow
- `Progress.tsx` - Progress bar with ARIA support

---

## Component Categories & When to Use

### 1. Form Components

#### Select Dropdown (RECOMMENDED over native `<select>`)

**When to Use**:

- Any dropdown with 3+ options
- Mobile-friendly selection needed
- Custom styling required
- Keyboard navigation important

**Installation**:

```bash
npm install @radix-ui/react-select
```

**Implementation Pattern**:

```tsx
// js/components/ui/select.tsx
import * as SelectPrimitive from "@radix-ui/react-select";
import { CheckIcon, ChevronDownIcon } from "@radix-ui/react-icons";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={`cat-select-trigger ${className ?? ""}`.trim()}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon className="cat-select-icon">
      <ChevronDownIcon />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = "SelectTrigger";

export const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={`cat-select-content ${className ?? ""}`.trim()}
      position={position}
      {...props}
    >
      <SelectPrimitive.Viewport className="cat-select-viewport">
        {children}
      </SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = "SelectContent";

export const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={`cat-select-item ${className ?? ""}`.trim()}
    {...props}
  >
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    <SelectPrimitive.ItemIndicator className="cat-select-indicator">
      <CheckIcon />
    </SelectPrimitive.ItemIndicator>
  </SelectPrimitive.Item>
));
SelectItem.displayName = "SelectItem";
```

**Usage Example**:

```tsx
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";

<Select value={value} onValueChange={setValue}>
  <SelectTrigger>
    <SelectValue placeholder="Select an option" />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="option1">Option 1</SelectItem>
    <SelectItem value="option2">Option 2</SelectItem>
    <SelectItem value="option3">Option 3</SelectItem>
  </SelectContent>
</Select>;
```

**Key Features**:

- Full keyboard navigation (Arrow keys, Home, End, Escape)
- Typeahead search
- Touch-friendly
- Accessible (ARIA compliant)
- Custom styling (no browser limitations)

---

#### Form with Validation (RECOMMENDED for all forms)

**When to Use**:

- Any form with validation requirements
- Forms needing accessible error messages
- Server-side validation support needed
- Complex multi-field forms

**Installation**:

```bash
npm install @radix-ui/react-form @radix-ui/react-label
```

**Implementation Pattern**:

```tsx
// js/components/ui/form.tsx
import * as FormPrimitive from "@radix-ui/react-form";

export const Form = FormPrimitive.Root;
export const FormField = FormPrimitive.Field;
export const FormLabel = FormPrimitive.Label;
export const FormControl = FormPrimitive.Control;
export const FormMessage = FormPrimitive.Message;
export const FormSubmit = FormPrimitive.Submit;
export const FormValidityState = FormPrimitive.ValidityState;
```

**Usage Example**:

```tsx
import {
  Form,
  FormField,
  FormLabel,
  FormControl,
  FormMessage,
  FormSubmit,
} from "@/components/ui/form";

<Form.Root
  onSubmit={(e) => {
    e.preventDefault();
    const formData = Object.fromEntries(new FormData(e.currentTarget));
    void handleSubmit(formData);
  }}
>
  <FormField name="email" serverInvalid={serverErrors?.email}>
    <FormLabel className="cat-field__label">
      {__("Email Address", "context-alt-text")}
    </FormLabel>

    <FormControl asChild>
      <input className="cat-field__input" type="email" required />
    </FormControl>

    {/* Built-in validation */}
    <FormMessage match="valueMissing" className="cat-field__error">
      {__("Please enter your email", "context-alt-text")}
    </FormMessage>

    {/* Custom validation */}
    <FormMessage
      match={(value) => !value.includes("@")}
      className="cat-field__error"
    >
      {__("Please provide a valid email address", "context-alt-text")}
    </FormMessage>

    {/* Server-side validation */}
    <FormMessage match="typeMismatch" forceMatch={serverErrors?.email}>
      {__("This email is already registered", "context-alt-text")}
    </FormMessage>
  </FormField>

  <FormSubmit asChild>
    <button className="cat-button cat-button--primary">
      {__("Submit", "context-alt-text")}
    </button>
  </FormSubmit>
</Form.Root>;
```

**Key Features**:

- Native Constraint Validation API integration
- Automatic ARIA error associations
- Focus management (moves to first invalid field)
- `data-valid` / `data-invalid` attributes for styling
- Server-side error support
- Custom async validation

**Validation Match Types**:

- `valueMissing` - Required field is empty
- `typeMismatch` - Input doesn't match type (e.g., invalid email)
- `patternMismatch` - Doesn't match pattern attribute
- `tooLong` / `tooShort` - Length constraints
- `rangeOverflow` / `rangeUnderflow` - Number range
- `stepMismatch` - Doesn't match step attribute
- `badInput` - Browser can't parse input
- Custom function: `match={(value, formData) => boolean | Promise<boolean>}`

---

#### Label (ALWAYS use with form controls)

**When to Use**:

- Every form input, select, textarea
- Any interactive control that needs a text label
- Replacing native `<label>` for better control

**Installation**:

```bash
npm install @radix-ui/react-label
```

**Implementation Pattern**:

```tsx
// js/components/ui/label.tsx
import * as LabelPrimitive from "@radix-ui/react-label";

export const Label = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={`cat-label ${className ?? ""}`.trim()}
    {...props}
  />
));
Label.displayName = "Label";
```

**Usage Example**:

```tsx
import { Label } from "@/components/ui/label";

{/* Method 1: Wrapping */}
<Label>
    {__("Username", "context-alt-text")}
    <input type="text" name="username" />
</Label>

{/* Method 2: htmlFor */}
<Label htmlFor="username">
    {__("Username", "context-alt-text")}
</Label>
<input id="username" type="text" name="username" />
```

---

### 2. Overlay Components

#### Dialog / Modal (RECOMMENDED for all modals)

**When to Use**:

- Confirmation dialogs
- Form modals
- Image previews
- Alert messages
- Any overlay that requires user interaction

**Installation**:

```bash
npm install @radix-ui/react-dialog
```

**Implementation Pattern**:

```tsx
// js/components/ui/dialog.tsx
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Cross2Icon } from "@radix-ui/react-icons";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogPortal = DialogPrimitive.Portal;
export const DialogClose = DialogPrimitive.Close;

export const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={`cat-dialog-overlay ${className ?? ""}`.trim()}
    {...props}
  />
));
DialogOverlay.displayName = "DialogOverlay";

export const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={`cat-dialog-content ${className ?? ""}`.trim()}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="cat-dialog-close">
        <Cross2Icon />
        <span className="screen-reader-text">
          {__("Close", "context-alt-text")}
        </span>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPortal>
));
DialogContent.displayName = "DialogContent";

export const DialogTitle = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={`cat-dialog-title ${className ?? ""}`.trim()}
    {...props}
  />
));
DialogTitle.displayName = "DialogTitle";

export const DialogDescription = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={`cat-dialog-description ${className ?? ""}`.trim()}
    {...props}
  />
));
DialogDescription.displayName = "DialogDescription";
```

**Usage Example**:

```tsx
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

<Dialog open={open} onOpenChange={setOpen}>
  <DialogTrigger asChild>
    <button className="cat-button">
      {__("Open Dialog", "context-alt-text")}
    </button>
  </DialogTrigger>

  <DialogContent>
    <DialogTitle>{__("Confirm Action", "context-alt-text")}</DialogTitle>

    <DialogDescription>
      {__("Are you sure you want to proceed?", "context-alt-text")}
    </DialogDescription>

    <div className="cat-dialog-actions">
      <button onClick={() => setOpen(false)}>
        {__("Cancel", "context-alt-text")}
      </button>
      <button onClick={handleConfirm}>
        {__("Confirm", "context-alt-text")}
      </button>
    </div>
  </DialogContent>
</Dialog>;
```

**Key Features**:

- Focus trap (can't tab outside)
- Scroll lock on body
- ESC key closes dialog
- Click outside to close (optional)
- ARIA announcements
- Portal rendering (no z-index issues)
- Modal and non-modal modes

---

#### Popover (for non-modal overlays)

**When to Use**:

- Date pickers
- Color pickers
- Rich menus
- Dropdowns that don't block interaction with rest of page

**Installation**:

```bash
npm install @radix-ui/react-popover
```

**Key Difference from Dialog**: Non-modal (doesn't trap focus, no overlay)

---

### 3. Feedback Components

#### Tooltip (AVAILABLE - already installed)

**When to Use**:

- Icon buttons without visible labels
- Abbreviated text needing clarification
- Additional context for any interactive element
- Status indicators needing explanation

**Usage Example**:

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
      <button className="cat-button cat-button--icon">
        <RefreshIcon />
        <span className="screen-reader-text">
          {__("Refresh", "context-alt-text")}
        </span>
      </button>
    </TooltipTrigger>

    <TooltipContent side="top">
      {__("Refresh the roster data", "context-alt-text")}
    </TooltipContent>
  </TooltipRoot>
</TooltipProvider>;
```

**Best Practices**:

- Always include screen reader text in the trigger
- Keep tooltip text concise (1-2 sentences max)
- Use `side` prop to control positioning
- Wrap app root with `TooltipProvider` once

---

#### Progress (AVAILABLE - already installed)

**When to Use**:

- File uploads
- Long-running operations
- Multi-step processes
- Loading indicators with known duration

**Usage Example**:

```tsx
import { Progress } from "@/components/ui/progress";

<Progress value={progress} max={100} />;
```

---

### 4. Navigation Components

#### Tabs

**When to Use**:

- Switching between views without navigation
- Organizing related content sections
- Dashboard layouts with multiple panels

**Installation**:

```bash
npm install @radix-ui/react-tabs
```

**Usage Pattern**:

```tsx
import * as Tabs from "@radix-ui/react-tabs";

<Tabs.Root defaultValue="tab1">
  <Tabs.List className="cat-tabs-list">
    <Tabs.Trigger value="tab1">
      {__("Overview", "context-alt-text")}
    </Tabs.Trigger>
    <Tabs.Trigger value="tab2">
      {__("Details", "context-alt-text")}
    </Tabs.Trigger>
  </Tabs.List>

  <Tabs.Content value="tab1">{/* Tab 1 content */}</Tabs.Content>

  <Tabs.Content value="tab2">{/* Tab 2 content */}</Tabs.Content>
</Tabs.Root>;
```

**Key Features**:

- Keyboard navigation (Arrow keys)
- ARIA roles and states
- Controlled or uncontrolled
- Automatic or manual activation

---

#### Accordion

**When to Use**:

- FAQ sections
- Collapsible form sections
- Nested content organization
- Progressive disclosure

**Installation**:

```bash
npm install @radix-ui/react-accordion
```

**Key Features**:

- Single or multiple items expanded
- Smooth animations
- Keyboard navigation
- ARIA compliant

---

### 5. Data Display Components

#### Separator (AVAILABLE - already installed)

**When to Use**:

- Visual dividers between sections
- Toolbar separators
- Menu item groups
- Any horizontal or vertical divider

**Usage Pattern**:

```tsx
import { Separator } from "@radix-ui/react-separator";

<Separator orientation="horizontal" className="cat-separator" />
<Separator orientation="vertical" className="cat-separator" />
```

---

### 6. Advanced Input Components

#### Switch (toggle)

**When to Use**:

- Boolean settings
- Feature toggles
- On/off states

**Installation**:

```bash
npm install @radix-ui/react-switch
```

---

#### Radio Group

**When to Use**:

- Mutually exclusive options (3-5 choices)
- Better UX than select for small sets
- Visual importance of showing all options

**Installation**:

```bash
npm install @radix-ui/react-radio-group
```

---

#### Checkbox

**When to Use**:

- Multiple selection
- Agree to terms
- Opt-in/opt-out features

**Installation**:

```bash
npm install @radix-ui/react-checkbox
```

---

#### Slider

**When to Use**:

- Numeric ranges
- Volume controls
- Opacity/transparency
- Any continuous value selection

**Installation**:

```bash
npm install @radix-ui/react-slider
```

---

## Common Patterns & Best Practices

### Pattern 1: Composing with asChild

The `asChild` prop allows Radix primitives to merge with your custom components:

```tsx
{
  /* Radix primitive renders as your Button component */
}
<Dialog.Trigger asChild>
  <Button variant="primary">{__("Open Dialog", "context-alt-text")}</Button>
</Dialog.Trigger>;

{
  /* Radix primitive renders as a custom link */
}
<Tooltip.Trigger asChild>
  <a href="/help" className="cat-link">
    {__("Help", "context-alt-text")}
  </a>
</Tooltip.Trigger>;
```

**When to use**: Any time you want Radix behavior on an existing component

---

### Pattern 2: Controlled vs Uncontrolled

Most Radix primitives support both modes:

```tsx
{
  /* Uncontrolled (Radix manages state) */
}
<Dialog.Root defaultOpen={false}>{/* ... */}</Dialog.Root>;

{
  /* Controlled (you manage state) */
}
<Dialog.Root open={isOpen} onOpenChange={setIsOpen}>
  {/* ... */}
</Dialog.Root>;
```

**When to use controlled**: When you need to coordinate with other state, validate, or prevent closing

---

### Pattern 3: Styling with Data Attributes

Radix adds `data-*` attributes for styling based on state:

```scss
// Dialog overlay animations
.cat-dialog-overlay[data-state="open"] {
  animation: fadeIn 200ms ease-out;
}

.cat-dialog-overlay[data-state="closed"] {
  animation: fadeOut 200ms ease-in;
}

// Select item states
.cat-select-item[data-highlighted] {
  background-color: var(--color-primary-50);
}

.cat-select-item[data-disabled] {
  opacity: 0.5;
  cursor: not-allowed;
}

// Form field states
.cat-field__label[data-invalid] {
  color: var(--color-error);
}

.cat-field__input[data-invalid] {
  border-color: var(--color-error);
}
```

**Available data attributes**:

- `data-state` - "open" | "closed"
- `data-disabled` - Present when disabled
- `data-highlighted` - Present when keyboard-highlighted
- `data-invalid` - Present when form field is invalid
- `data-valid` - Present when form field is valid
- `data-placeholder` - Present when showing placeholder

---

### Pattern 4: Portal Rendering

Most overlay components use portals to avoid z-index issues:

```tsx
{
  /* Default: portals to document.body */
}
<Dialog.Portal>
  <Dialog.Content>{/* ... */}</Dialog.Content>
</Dialog.Portal>;

{
  /* Custom container */
}
<Dialog.Portal container={customContainer}>
  <Dialog.Content>{/* ... */}</Dialog.Content>
</Dialog.Portal>;

{
  /* Disable portal (render in place) */
}
<Select.Content position="item-aligned">
  {/* No portal needed for item-aligned positioning */}
</Select.Content>;
```

---

### Pattern 5: Accessibility Requirements

**ALWAYS include**:

1. **Labels for interactive elements**:

   ```tsx
   {/* Visible label */}
   <Label htmlFor="email">{__("Email", "context-alt-text")}</Label>
   <input id="email" type="email" />

   {/* Or aria-label for icon buttons */}
   <button aria-label={__("Close dialog", "context-alt-text")}>
       <CrossIcon />
   </button>
   ```

2. **Screen reader text for icon-only controls**:

   ```tsx
   <button className="cat-button cat-button--icon">
     <RefreshIcon />
     <span className="screen-reader-text">
       {__("Refresh", "context-alt-text")}
     </span>
   </button>
   ```

3. **Dialog titles and descriptions**:

   ```tsx
   <Dialog.Content>
     <Dialog.Title>{__("Delete Item", "context-alt-text")}</Dialog.Title>
     <Dialog.Description>
       {__("This action cannot be undone.", "context-alt-text")}
     </Dialog.Description>
   </Dialog.Content>
   ```

4. **Keyboard navigation support**:
   - Test with Tab, Shift+Tab, Arrow keys, Enter, Escape
   - Ensure focus is visible
   - Verify focus trap in modals

---

## WordPress Integration Notes

### Internationalization

**ALWAYS wrap user-visible strings**:

```tsx
import { __ } from "@wordpress/i18n";

<Label>{__("First Name", "context-alt-text")}</Label>
<Dialog.Title>{__("Confirm Delete", "context-alt-text")}</Dialog.Title>
<FormMessage>{__("This field is required", "context-alt-text")}</FormMessage>
```

---

### WordPress Media Library Integration

When using WordPress media modals alongside Radix UI dialogs:

```tsx
const openMediaModal = () => {
  // WordPress media frame
  const frame = wp.media({
    title: __("Select Avatar", "context-alt-text"),
    button: { text: __("Use this image", "context-alt-text") },
    multiple: false,
  });

  frame.on("select", () => {
    const attachment = frame.state().get("selection").first().toJSON();
    setAvatarUrl(attachment.url);
  });

  frame.open();
};

// Radix UI Dialog for preview
<Dialog.Root>
  <Dialog.Trigger asChild>
    <button onClick={openMediaModal}>
      {__("Select Avatar", "context-alt-text")}
    </button>
  </Dialog.Trigger>
</Dialog.Root>;
```

---

## Testing Radix UI Components

### Unit Tests (Vitest + Testing Library)

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
    </Dialog>
  );

  // Dialog should be closed initially
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  // Open dialog
  await user.click(screen.getByText("Open"));
  expect(screen.getByRole("dialog")).toBeInTheDocument();

  // Close dialog
  await user.click(screen.getByText("Close"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
```

### Accessibility Tests

```tsx
import { axe } from "vitest-axe";

test("select has no accessibility violations", async () => {
  const { container } = render(
    <Select>
      <SelectTrigger>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="1">Item 1</SelectItem>
      </SelectContent>
    </Select>
  );

  const results = await axe(container);
  expect(results).toHaveNoViolations();
});
```

---

## Migration Checklist

When replacing a custom component with Radix UI:

1. [ ] Install the Radix primitive package
2. [ ] Create wrapper component in `js/components/ui/`
3. [ ] Apply WordPress CSS classes (BEM: `cat-*`)
4. [ ] Add internationalization (`__()` for all strings)
5. [ ] Add TypeScript types (extend Radix primitive types)
6. [ ] Create Storybook story (if using Storybook)
7. [ ] Write unit tests (behavior, not implementation)
8. [ ] Run accessibility audit (`axe-core`)
9. [ ] Test keyboard navigation manually
10. [ ] Update consuming components
11. [ ] Verify all tests pass
12. [ ] Document usage in component file

---

## Bundle Size Considerations

**Current Radix UI packages** (~15 kB total):

- `@radix-ui/react-progress`: 3.02 kB
- `@radix-ui/react-separator`: 1.66 kB
- `@radix-ui/react-slot`: 2.48 kB
- `@radix-ui/react-tooltip`: 7.75 kB

**Recommended additions**:

- `@radix-ui/react-select`: 34.89 kB (replaces all native `<select>`)
- `@radix-ui/react-form`: 5.22 kB (replaces custom validation)
- `@radix-ui/react-dialog`: 17.93 kB (replaces all modals)
- `@radix-ui/react-label`: 1.66 kB (required for forms)

**Total estimated bundle increase**: ~60-65 kB (gzipped: ~18-20 kB)

**ROI**: Eliminates need for custom implementations, reduces maintenance burden, improves accessibility

---

## Quick Reference: Component Decision Matrix

| Use Case                 | Radix Primitive                | Bundle Size | Priority | Notes                  |
| ------------------------ | ------------------------------ | ----------- | -------- | ---------------------- |
| Dropdown with 3+ options | `@radix-ui/react-select`       | 34.89 kB    | HIGH     | Replace all `<select>` |
| Any form                 | `@radix-ui/react-form`         | 5.22 kB     | HIGH     | Built-in validation    |
| Modal/Dialog             | `@radix-ui/react-dialog`       | 17.93 kB    | HIGH     | Focus management       |
| Form labels              | `@radix-ui/react-label`        | 1.66 kB     | HIGH     | Required for forms     |
| Icon tooltips            | `@radix-ui/react-tooltip`      | INSTALLED   | HIGH     | Already available      |
| Status badges            | Add tooltip to existing        | +0 kB       | MEDIUM   | Enhance current        |
| Tabs/Panels              | `@radix-ui/react-tabs`         | 6.19 kB     | MEDIUM   | Multi-view layouts     |
| Collapsible sections     | `@radix-ui/react-accordion`    | 9.14 kB     | MEDIUM   | FAQ, nested content    |
| Delete confirmations     | `@radix-ui/react-alert-dialog` | 18.05 kB    | LOW      | Can use Dialog         |
| On/off toggle            | `@radix-ui/react-switch`       | 3.02 kB     | LOW      | Boolean settings       |
| 3-5 options              | `@radix-ui/react-radio-group`  | 7.77 kB     | LOW      | Better than select     |
| Multi-select             | `@radix-ui/react-checkbox`     | 3.45 kB     | LOW      | Multiple options       |
| Numeric range            | `@radix-ui/react-slider`       | 5.89 kB     | LOW      | Volume, opacity        |

---

## Resources

### Official Documentation

- [Radix UI Primitives](https://www.radix-ui.com/primitives/docs/overview/introduction) - Main documentation
- [GitHub Repository](https://github.com/radix-ui/primitives) - Source code and issues

### Component-Specific Docs

- [Select](https://www.radix-ui.com/primitives/docs/components/select)
- [Form](https://www.radix-ui.com/primitives/docs/components/form)
- [Dialog](https://www.radix-ui.com/primitives/docs/components/dialog)
- [Label](https://www.radix-ui.com/primitives/docs/components/label)
- [Tooltip](https://www.radix-ui.com/primitives/docs/components/tooltip)

### Community Examples

- [shadcn/ui](https://ui.shadcn.com/) - Production-ready components built on Radix UI
- [Radix UI Discord](https://discord.com/invite/7Xb99uG) - Community support

---

## Approval Process

**Before implementing a new UI component**:

1. Check this guide for existing Radix primitive
2. If primitive exists: Use it (do not build custom)
3. If no primitive exists: Evaluate if pattern is common enough to warrant a new dependency
4. Discuss in architecture review if adding a new Radix primitive
5. Update this guide when new primitives are adopted

**Exception Process**:

- Custom implementations require architectural approval
- Justification must include accessibility, bundle size, and maintenance considerations
- Document decision in component file and link to approval discussion

---

## Maintenance Notes

**This guide should be updated when**:

- New Radix UI primitives are adopted
- Wrapper components are created in `js/components/ui/`
- Usage patterns change based on team experience
- Breaking changes in Radix UI versions
- New accessibility requirements emerge

**Review Frequency**: Quarterly or when major Radix UI version releases

**Owner**: Frontend Architecture Team

---

## Appendix: Full Radix UI Primitive Catalog

For reference, here's the complete list of available Radix UI primitives (as of October 2025):

### Overlay

- Accordion
- Alert Dialog
- Collapsible
- Context Menu
- Dialog
- Dropdown Menu
- Hover Card
- Menubar
- Navigation Menu
- Popover
- Tooltip

### Form

- Checkbox
- Form
- Label
- Radio Group
- Select
- Slider
- Switch
- Toggle
- Toggle Group

### Navigation

- Tabs

### Data Display

- Avatar
- Progress
- Separator

### Utilities

- Aspect Ratio
- Scroll Area
- Visually Hidden

### Composition

- Slot (INSTALLED)

---

**END OF GUIDE**

For detailed analysis and migration roadmap, see: `docs/RADIX_UI_OPPORTUNITIES.md`
