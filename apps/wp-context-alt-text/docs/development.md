# Development Guide

This guide covers contributing to the Context Alt Text plugin, including development workflow, testing, code standards, and best practices.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [Component Development](#component-development)
- [Debugging](#debugging)
- [Contributing](#contributing)

---

## Getting Started

### Prerequisites

- **Node.js** >= 22.18.0 (use `nvm` or FNM)
- **PHP** >= 8.2
- **Composer** >= 2.0
- **WordPress** >= 6.0 (LocalWP recommended)

### Initial Setup

```bash
# Clone monorepo
git clone https://github.com/your-org/context-alt-text-monorepo.git
cd context-alt-text-monorepo/apps/wp-context-alt-text

# Install dependencies
npm install
composer install

# Switch to local development environment
./scripts/switch-env.sh local

# Set up LocalWP symlink (from LocalWP plugins directory)
ln -s /path/to/monorepo/apps/wp-context-alt-text context-alt-text

# Activate plugin
wp plugin activate context-alt-text
```

### Environment Setup

1. **Configure WordPress for development:**

    ```php
    // Add to wp-config.php
    define('WP_ENVIRONMENT_TYPE', 'development');
    define('WP_DEBUG', true);
    define('WP_DEBUG_LOG', true);
    define('WP_DEBUG_DISPLAY', false);
    ```

2. **Start recognition service (optional):**

    ```bash
    cd ../recognition-service
    ./scripts/start_recognition_local.sh
    ```

3. **Start Vite dev server:**
    ```bash
    cd apps/wp-context-alt-text
    npm run dev
    ```

---

## Development Workflow

### Feature Development

1. **Create feature branch:**

    ```bash
    git checkout -b feature/your-feature-name
    ```

2. **Switch to appropriate environment:**

    ```bash
    ./scripts/switch-env.sh local
    ```

3. **Start development servers:**

    ```bash
    npm run dev        # Vite dev server
    npm run storybook  # Component workbench (optional)
    ```

4. **Make changes:**
    - PHP code in `src/`
    - TypeScript/React in `js/`
    - Tests in `tests/` (PHP) or `js/**/*.test.ts` (TypeScript)

5. **Test your changes:**

    ```bash
    composer test      # PHP tests
    npm run test       # TypeScript tests
    ```

6. **Commit and push:**
    ```bash
    git add .
    git commit -m "feat: add your feature"
    git push origin feature/your-feature-name
    ```

### Hot Module Replacement (HMR)

Vite provides instant feedback during development:

- **PHP changes:** Reload WordPress admin page
- **TypeScript/React changes:** Automatically update in browser (HMR)
- **CSS/SCSS changes:** Automatically update without page reload

---

## Code Standards

### PHP Standards

**PSR-12 Extended Coding Style:**

```php
<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

/**
 * Recognition service settings.
 */
class RecognitionSettings
{
    public function __construct(
        private SettingsRepository $settingsRepository
    ) {
    }

    public function getBaseUrl(): string
    {
        // Check environment variable first
        $url = $this->getEnv('CAT_RECOGNITION_BASE_URL');

        if (empty($url)) {
            $settings = $this->settingsRepository->getRecognitionSettings();
            $url = $settings['baseUrl'] ?? '';
        }

        return $url;
    }
}
```

**Best Practices:**

- ✅ Type declarations on all methods
- ✅ Property promotion in constructors
- ✅ Dependency injection over global state
- ✅ Return types on all methods
- ✅ Docblocks for public APIs
- ✅ Use WordPress coding standards where applicable

### TypeScript Standards

**TypeScript 5.x with strict mode:**

```typescript
import { useState, useEffect } from 'react';
import type { RecognitionStatus } from '../types';

interface RecognitionPanelProps {
  attachmentId: number;
  onSuccess?: (observations: Observation[]) => void;
  onError?: (error: Error) => void;
}

export function RecognitionPanel({
  attachmentId,
  onSuccess,
  onError,
}: RecognitionPanelProps): JSX.Element {
  const [status, setStatus] = useState<RecognitionStatus>('idle');

  useEffect(() => {
    // Component logic
  }, [attachmentId]);

  return <div>{/* Component JSX */}</div>;
}
```

**Best Practices:**

- ✅ Explicit types for props, state, and returns
- ✅ Use `interface` for object shapes
- ✅ Use `type` for unions and primitives
- ✅ Functional components with hooks
- ✅ Extract complex logic into custom hooks
- ✅ Use `const` for immutable values

### React Standards

**Component Structure:**

```typescript
// 1. Imports
import { useState, useEffect } from 'react';
import { Button } from '../ui/button';
import type { Props } from './types';

// 2. Types/Interfaces
interface ComponentProps {
  // Props definition
}

// 3. Component
export function Component({ prop1, prop2 }: ComponentProps) {
  // 4. Hooks
  const [state, setState] = useState();

  // 5. Effects
  useEffect(() => {
    // Effect logic
  }, [dependencies]);

  // 6. Handlers
  const handleClick = () => {
    // Handler logic
  };

  // 7. Render
  return <div>{/* JSX */}</div>;
}
```

**Best Practices:**

- ✅ Keep components small and focused
- ✅ Extract reusable UI to `js/components/ui/`
- ✅ Extract feature logic to custom hooks
- ✅ Use Radix UI primitives for accessibility
- ✅ Use SCSS modules for styling
- ✅ Add Storybook stories for all components

---

## Testing

### PHP Testing (PHPUnit)

**Running Tests:**

```bash
# All tests
composer test

# Specific test file
composer test -- tests/Recognition/RecognitionSettingsTest.php

# Specific test method
composer test -- --filter testEnvironmentVariableTakesPrecedence

# With coverage
composer test -- --coverage-html coverage/
```

**Writing Tests:**

```php
<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Recognition;

use ContextAltText\Recognition\RecognitionSettings;
use PHPUnit\Framework\TestCase;

/**
 * @covers \ContextAltText\Recognition\RecognitionSettings
 */
class RecognitionSettingsTest extends TestCase
{
    public function testEnvironmentVariableTakesPrecedence(): void
    {
        // Arrange
        putenv('CAT_RECOGNITION_BASE_URL=http://env.test');
        $settings = new RecognitionSettings($this->mockRepository);

        // Act
        $url = $settings->getBaseUrl();

        // Assert
        $this->assertEquals('http://env.test', $url);
    }
}
```

**Test Structure:**

- `tests/unit/` - Unit tests (isolated, fast)
- `tests/Integration/` - Integration tests (multiple components)
- `tests/Recognition/` - Recognition service tests
- `tests/Roster/` - Roster management tests
- `tests/Support/` - Utility and helper tests

### TypeScript Testing (Vitest)

**Running Tests:**

```bash
# All tests
npm run test

# Watch mode
npm run test:watch

# With coverage
npm run test:coverage

# Specific file
npm run test -- src/components/Button.test.tsx
```

**Writing Tests:**

```typescript
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from './Button';

describe('Button', () => {
  it('renders with text', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('calls onClick when clicked', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click me</Button>);

    fireEvent.click(screen.getByText('Click me'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
```

### Manual Testing

**WP-CLI Commands:**

```bash
# Recognition service
wp cat-recognition health
wp cat-recognition analyze 123

# Roster management
wp cat-roster status
wp cat-roster sync

# Face detection and clustering
wp cat-faces scan --attachment-ids=123,456
wp cat-faces stats
wp cat-faces list-clusters
wp cat-faces cluster-detail <cluster-id>
wp cat-faces clear-unknown --yes

# Configuration
wp option get cat_settings --format=json
```

**Browser Testing:**

1. Visit WordPress admin dashboard
2. Navigate to **Context Alt Text → Workbench**
3. Upload test image with faces
4. Click **"Scan for Faces"** to trigger detection
5. View clustered faces in **Unknown People** panel
6. Test cluster detail view and labeling workflow
7. Verify roster assignment

---

## Face Clustering Architecture

### Overview

The plugin implements automatic face clustering using embedding-based similarity. Faces are detected via the recognition service (InsightFace), and 512-dimensional embeddings are stored in WordPress for local clustering.

### Components

**Domain Layer (`src/Domain/Clustering/`):**
- `ClusteringEngine.php` - Interface for clustering operations
- `ClusteringService.php` - Main clustering logic with local algorithm
- `UnknownFace.php` - Entity representing detected face with embedding

**Infrastructure Layer (`src/Infrastructure/`):**
- `UnknownFaceRepository.php` - Database CRUD operations
- `UnknownFaceTableInstaller.php` - Schema management with `embedding_vector` column

**Jobs & Recognition (`src/Jobs/`, `src/Recognition/`):**
- `FaceDetectionJob.php` - Persists faces with IoU duplicate detection
- `FaceDetectionPipeline.php` - Interface for detection strategies
- `RecognitionServiceFaceDetectionPipeline.php` - Calls recognition API
- `SynchronousFaceDetectionQueue.php` - Triggers clustering after batch
- `ScanController.php` - REST endpoint for batch scanning
- `ClusterController.php` - REST endpoints for cluster operations
- `CachedFaceThumbnailProvider.php` - 112x112px thumbnail generation

**Frontend (`js/`):**
- `components/workbench/UnknownPeoplePanel.tsx` - Main clustering UI
- `components/workbench/ClusterCard.tsx` - Individual cluster display
- `components/workbench/ClusterDetailView.tsx` - Cluster inspection view
- `components/workbench/ClusterConfirmationModal.tsx` - Labeling workflow
- `hooks/useUnknownClusters.ts` - Fetch grouped faces
- `hooks/useClusterDetail.ts` - Fetch cluster details
- `hooks/useFaceScan.ts` - Trigger batch face detection

### Clustering Algorithm

**Single-Linkage Hierarchical Clustering:**
- Uses cosine similarity on L2-normalized 512-dim embeddings
- Threshold: 0.45 for merging clusters
- Runs locally in PHP (no remote clustering endpoint)
- Triggered automatically after face detection batch completes

**Implementation:**
```php
// In ClusteringService::clusterEmbeddingsLocally()
1. Load all unknown faces with embeddings
2. Normalize embedding vectors (L2 normalization)
3. Compute pairwise cosine similarities
4. Merge clusters if similarity > 0.45
5. Update cluster assignments in database
```

### Database Schema

**Table: `wp_cat_unknown_faces`**
- `embedding_vector` - MEDIUMTEXT, stores JSON array of floats (~5KB per face)
- `embedding_id` - VARCHAR(255), unique identifier from recognition service
- `cluster_id` - VARCHAR(255), NULL for unclustered faces
- Auto-migration adds `embedding_vector` column if missing

### Workflow

1. **Face Detection:**
   - User clicks "Scan for Faces" button
   - Frontend calls `POST /wp-json/cat/v1/recognition/scan`
   - `ScanController` enqueues batch job
   - `FaceDetectionJob` processes each attachment
   - Recognition service returns bounding boxes + embeddings
   - Embeddings stored as JSON in `embedding_vector` column

2. **Automatic Clustering:**
   - `SynchronousFaceDetectionQueue` triggers clustering after batch
   - `ClusteringService::clusterUnknownFaces()` called
   - Local clustering algorithm groups similar faces
   - Cluster IDs assigned to faces

3. **UI Display:**
   - Frontend fetches clusters via `GET /wp-json/cat/v1/clusters`
   - `UnknownPeoplePanel` displays cluster cards
   - Each card shows thumbnail and face count

4. **Labeling:**
   - User clicks cluster to view details
   - `ClusterDetailView` shows all faces in cluster
   - User selects roster entry from suggestions
   - `ClusterConfirmationModal` confirms identity
   - All faces in cluster labeled with roster ID

### Testing

**Unit Tests:**
```bash
# Clustering logic
composer test -- tests/Domain/Clustering/ClusteringServiceTest.php

# Repository operations
composer test -- tests/Infrastructure/Repositories/UnknownFaceRepositoryTest.php

# Face detection
composer test -- tests/Jobs/FaceDetectionJobTest.php
```

**Integration Tests:**
```bash
# API endpoints
composer test -- tests/Recognition/ClusterControllerTest.php
composer test -- tests/Recognition/ScanControllerTest.php
```

**Frontend Tests:**
```bash
# React components
npm run test -- js/components/workbench/UnknownPeoplePanel.test.tsx

# Hooks
npm run test -- js/hooks/useUnknownClusters.test.ts
```

### Configuration

**Clustering Threshold:**
```php
// In ClusteringService.php
const LOCAL_CLUSTER_THRESHOLD = 1000; // Always use local clustering
const SIMILARITY_THRESHOLD = 0.45;    // Merge if similarity > 0.45
```

**Database Limits:**
- Embedding vector: ~5KB per face (512 floats as JSON)
- MEDIUMTEXT column: Max 16MB (~3,200 faces per table)
- Consider archiving old faces if approaching limits

### Troubleshooting

**No embeddings persisted:**
- Check recognition service includes `embedding` field in response
- Verify `scene_analysis_service.py` lines 73-85 for embedding data
- Test: `curl http://localhost:7860/api/v0/recognition/analyze -X POST ...`

**Clustering not working:**
- Check `LOCAL_CLUSTER_THRESHOLD` is set high enough
- Verify automatic clustering trigger in `SynchronousFaceDetectionQueue`
- Test: `wp cat-faces stats` should show "Clustered: X (Y%)"

**Missing thumbnails:**
- Check crop dimensions (minimum 28x28px for 112x112px resize)
- Verify WordPress image functions available
- Fallback placeholder (👤) shows for failed crops

---

## Component Development

### Storybook Workflow

```bash
# Start Storybook
npm run storybook

# Build static Storybook
npm run storybook:build
```

**Creating Stories:**

```typescript
// Button.stories.tsx
import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "./Button";

const meta: Meta<typeof Button> = {
    title: "UI/Button",
    component: Button,
    argTypes: {
        variant: {
            control: "select",
            options: ["default", "primary", "secondary"],
        },
    },
};

export default meta;
type Story = StoryObj<typeof Button>;

export const Default: Story = {
    args: {
        children: "Button",
    },
};

export const Primary: Story = {
    args: {
        children: "Primary Button",
        variant: "primary",
    },
};

export const Loading: Story = {
    args: {
        children: "Loading...",
        disabled: true,
    },
};
```

**Story Guidelines:**

- ✅ Create stories for all component variants
- ✅ Include loading, empty, error states
- ✅ Document props with Storybook controls
- ✅ Add interaction tests for user actions
- ✅ Test accessibility with a11y addon

### Component Guidelines

**Reusable UI Components:**

Place in `js/components/ui/`:

- Buttons, inputs, dialogs, dropdowns
- Use Radix UI primitives
- Style with SCSS modules
- Export as named exports

**Feature Components:**

Place in `js/components/<feature>/`:

- Dashboard-specific components
- Feature-specific logic
- Compose UI components

---

## Debugging

### PHP Debugging

**WordPress Debug Logs:**

```bash
# View live logs
tail -f /path/to/wp-content/uploads/cat-logs/debug-$(date +%Y-%m-%d).log

# Search logs
grep "Recognition" /path/to/wp-content/uploads/cat-logs/*.log
```

**Adding Debug Logging:**

```php
use ContextAltText\Shared\Logger;

// In your class
Logger::debug('Recognition started', [
    'attachmentId' => $attachmentId,
    'settings' => $settings,
]);
```

**Xdebug Setup:**

```ini
; php.ini
xdebug.mode=debug
xdebug.start_with_request=yes
xdebug.client_host=localhost
xdebug.client_port=9003
```

### TypeScript Debugging

**Browser DevTools:**

- Vite provides source maps for debugging
- Use React DevTools for component inspection
- Check console for logger output

**Adding Debug Logging:**

```typescript
import { createLogger } from "../admin/logger";

const logger = createLogger("RecognitionPanel");

logger.debug("Recognition triggered", { attachmentId });
logger.info("Recognition complete", { observations });
logger.error("Recognition failed", error);
```

**VS Code Debugging:**

Add to `.vscode/launch.json`:

```json
{
    "type": "chrome",
    "request": "launch",
    "name": "Debug WordPress Admin",
    "url": "http://localhost:10008/wp-admin",
    "webRoot": "${workspaceFolder}/apps/wp-context-alt-text"
}
```

---

## Contributing

### Pull Request Process

1. **Create feature branch** from `main`
2. **Make changes** following code standards
3. **Add tests** for new functionality
4. **Update documentation** if needed
5. **Run tests** and ensure they pass
6. **Build production assets** (`npm run build`)
7. **Create pull request** with description

### PR Checklist

- [ ] Code follows PSR-12 (PHP) and TypeScript standards
- [ ] All tests pass (`composer test` and `npm run test`)
- [ ] New functionality has tests
- [ ] Documentation updated (README, JSDoc, PHPDoc)
- [ ] Storybook stories added for new components
- [ ] Production assets built and committed
- [ ] No console errors or warnings
- [ ] Tested manually in WordPress

### Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add roster import from CSV
fix: resolve recognition timeout issue
docs: update configuration guide
test: add tests for RecognitionSettings
refactor: simplify observation matching logic
chore: update dependencies
```

---

## Performance Considerations

### PHP Performance

- ✅ Use WordPress transients for caching
- ✅ Batch database queries
- ✅ Use dependency injection (avoid global state)
- ✅ Profile with Query Monitor plugin

### Frontend Performance

- ✅ Use React.memo for expensive components
- ✅ Debounce/throttle user input
- ✅ Lazy load components with React.lazy
- ✅ Optimize images and assets

---

## Support

- **Issues:** [GitHub Issues](https://github.com/your-org/context-alt-text-monorepo/issues)
- **Discussions:** [GitHub Discussions](https://github.com/your-org/context-alt-text-monorepo/discussions)
- **Documentation:** [`docs/`](.)
