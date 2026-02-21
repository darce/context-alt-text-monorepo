---
description: Create new service/component skeleton (scaffolding-first)
---

**Purpose**: Generate boilerplate for new Python services, React components, or hooks following scaffolding-first pattern.

**When to use**:

- Creating new domain service
- Adding new React component or hook
- Starting TDD cycle (scaffold → tests → implementation)

**Prerequisites**: Knowledge of what you're building

This workflow helps create new domain services or React components following the scaffolding-first pattern.

1. Ask what to scaffold: service (Python), component (React), or hook (React).

2. For a Python service, use your **`write_to_file`** tool to create a file at `apps/prototype-description-service/recognition/application/_new_service.py` with the following skeleton:

```python
"""
TODO: Rename this file and update class name.

New Service Skeleton - Scaffolding First Pattern
"""
from typing import Protocol


class NewServiceProtocol(Protocol):
    """Define the interface before implementation."""

    async def execute(self, input_data: str) -> str:
        """
        TODO: Document what this method does.

        Args:
            input_data: Description of input.

        Returns:
            Description of output.

        Raises:
            ValueError: When input is invalid.
        """
        ...


class NewService:
    """Implementation of NewServiceProtocol."""

    async def execute(self, input_data: str) -> str:
        raise NotImplementedError("TODO: Implement this method")
```
*(After creating: Rename file, update class name, and write tests first!)*

3. For a React component, use your **`write_to_file`** tool to create a file at `apps/prototype-wp-alt-context/js/admin/components/_NewComponent.tsx` with the following skeleton:

```tsx
/**
 * TODO: Rename this file and component.
 *
 * New Component Skeleton - Scaffolding First Pattern
 */

interface NewComponentProps {
  /** TODO: Document props */
  value: string;
}

export function NewComponent({ value }: NewComponentProps): JSX.Element {
  // TODO: Implement component
  return <div>NewComponent: {value}</div>;
}
```
*(After creating: Rename, add to index, and write tests first!)*
