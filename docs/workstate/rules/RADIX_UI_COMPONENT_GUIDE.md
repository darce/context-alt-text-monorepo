# Radix UI Component Guide (Project Conventions)

> **Library reference**: Review current docs for `@radix-ui/react-*` listed
> in [../maps/tech-stack.md](../maps/tech-stack.md#frontend-reactts) before starting work.
> This file covers only project-specific conventions.

Prefer Radix UI primitives over custom implementations for consistent, accessible components.

---

## Installed Packages

Ready to use in `js/components/ui/`:

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

1. `npm install @radix-ui/react-{component}`
2. Create wrapper in `js/components/ui/{component}.tsx`
3. BEM classes: `acx-{component}`, `acx-{component}--variant`
4. TypeScript types extending Radix props
5. Behavior tests + axe-core audit

---

## Project Conventions

- **All user-visible strings** must go through WordPress i18n: `__("Label", "alt-context")`
- **Always include screen reader text** in icon-only trigger buttons
- **Controlled dialogs** must wire `onOpenChange`; see [../instructions.md](../instructions.md) for the role semantics guard
- **Styling** uses data-state / data-highlighted / data-disabled attributes; apply `--acx-*` design tokens, not hex literals

---

## Resources

- [Radix UI Docs](https://www.radix-ui.com/primitives/docs/overview/introduction)
