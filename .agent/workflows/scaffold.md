---
description: Create new service/component skeleton (scaffolding-first)
---

**Purpose**: Generate boilerplate for new Python services, React components, or hooks following scaffolding-first pattern.

**When to use**:

- Creating new domain service
- Adding new React component or hook
- Starting TDD cycle (scaffold → tests → implementation)

**Prerequisites**: Knowledge of what you're building

This command helps create new domain services or React components following the scaffolding-first pattern.

1. Ask what to scaffold: service (Python), component (React), or hook (React)

2. For Python service, create skeleton:

```bash
cd apps/prototype-description-service
cat > recognition/application/_new_service.py << 'EOF'
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
EOF
echo "Created: recognition/application/_new_service.py"
echo "Next: Rename file, update class name, write tests first!"
```

3. For React component:

```bash
cd apps/prototype-wp-alt-context/js/admin
cat > components/_NewComponent.tsx << 'EOF'
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
EOF
echo "Created: components/_NewComponent.tsx"
echo "Next: Rename, add to index, write tests first!"
```
