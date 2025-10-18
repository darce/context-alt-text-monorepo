# Architectural Improvements Roadmap

**Project:** Context Alt Text WordPress Plugin  
**Date:** October 17, 2025  
**Status:** Beyond Immediate Refactoring - Strategic Architecture

**Context:** This document identifies architectural improvements beyond the immediate refactoring tasks in [REFACTORING_TASKS.md](REFACTORING_TASKS.md). These are strategic enhancements for long-term maintainability, scalability, and developer experience.

---

## 🎯 Executive Summary

### Current Architecture Assessment

**Strengths:**
- ✅ Clean Architecture / Hexagonal pattern
- ✅ Proper dependency injection via constructor
- ✅ PSR-4 autoloading
- ✅ Strong type safety (strict_types=1)
- ✅ Good separation of concerns

**Strategic Weaknesses:**
- 🔴 **Manual dependency wiring** (491-line bootstrap file)
- 🔴 **No dependency injection container**
- 🔴 **Circular dependency risk** (manual setter injection)
- 🟡 **Global function-based service locators**
- 🟡 **Mixed responsibility in bootstrap file**
- 🟡 **No event/message bus architecture**
- 🟡 **Limited testability** (hard to mock dependencies)

### Recommended Strategic Improvements

| Priority | Improvement | Impact | Effort | ROI |
|----------|-------------|--------|--------|-----|
| 🔴 Critical | Dependency Injection Container | High | High | Very High |
| 🔴 Critical | Service Provider Architecture | High | Medium | High |
| 🟡 High | Event/Message Bus | Medium | Medium | High |
| 🟡 High | Repository Pattern Refinement | Medium | Low | Medium |
| 🟢 Medium | Command/Query Separation (CQRS) | Medium | High | Medium |
| 🟢 Medium | Domain Events | Medium | Medium | Medium |
| 🟢 Low | Strategic Testing Architecture | Low | Medium | High |

---

## 🔴 CRITICAL IMPROVEMENT 1: Dependency Injection Container

### Current Problem

**Bootstrap File Analysis:** `context-alt-text.php` (491 lines)

```php
// Lines 142-459: Manual dependency construction and wiring
function context_alt_text(): ContextAltText
{
    static $instance = null;
    
    if ($instance instanceof ContextAltText) {
        return $instance;
    }
    
    // 300+ lines of manual wiring
    $scanner = new MissingAltTextScanner();
    $settingsRepository = context_alt_text_settings_repository();
    $featureFlags = new FeatureFlags($settingsRepository);
    $security = new Security();
    $rosterService = context_alt_text_roster_service($security);
    // ... 50+ more dependencies manually wired
    
    $instance = new ContextAltText(
        new Admin(/* 8 dependencies */),
        new Frontend(),
        new Api(/* 11 dependencies */),
        new Menu(/* 7 dependencies */),
        $rosterPage,
        new Template(),
        $featureFlags,
        new LifecycleManager($scanner),
        $scanner,
        $mediaPanel
    );
    
    return $instance;
}
```

**Issues:**
1. **Fragile:** Adding a dependency requires updating multiple files
2. **Error-Prone:** Easy to miss dependencies or wire them incorrectly
3. **Hard to Test:** Can't easily swap implementations
4. **Circular Dependencies:** Manual setter injection needed (line 163)
5. **No Lazy Loading:** All services instantiated on every request
6. **Poor Discoverability:** Hard to see what depends on what

### Recommended Solution: PHP-DI Container

**Why PHP-DI:**
- Industry-standard, battle-tested
- Autowiring support (automatically resolves dependencies)
- Lazy loading (instantiate only when needed)
- Easy to override for testing
- Minimal performance overhead
- Works great with WordPress

**Implementation Strategy:**

#### Step 1: Install PHP-DI

```bash
cd apps/wp-context-alt-text
composer require php-di/php-di "^7.0"
```

#### Step 2: Create Container Configuration

**Create:** `src/Infrastructure/ContainerConfig.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Infrastructure;

use DI\ContainerBuilder;
use Psr\Container\ContainerInterface;
use function DI\autowire;
use function DI\get;

final class ContainerConfig
{
    public static function build(): ContainerInterface
    {
        $builder = new ContainerBuilder();
        
        if (defined('WP_DEBUG') && !WP_DEBUG) {
            // Enable compilation in production
            $builder->enableCompilation(
                WP_CONTENT_DIR . '/cache/cat-container'
            );
        }
        
        $builder->addDefinitions(self::getDefinitions());
        
        return $builder->build();
    }
    
    private static function getDefinitions(): array
    {
        return [
            // Shared Services (Singletons)
            SettingsRepository::class => autowire()->lazy(),
            FeatureFlags::class => autowire()->lazy(),
            Security::class => autowire()->lazy(),
            Logger::class => autowire()->lazy(),
            
            // Recognition Services
            RecognitionSettings::class => autowire()->lazy(),
            RecognitionClient::class => autowire()->lazy(),
            RecognitionJobRepository::class => autowire()->lazy(),
            RecognitionObservationRepository::class => autowire()->lazy(),
            RecognitionJobService::class => autowire()->lazy(),
            
            // Roster Services
            RosterClient::class => autowire()->lazy(),
            RosterService::class => autowire()->lazy(),
            RosterTaxonomy::class => autowire()->lazy(),
            RosterSyncScheduler::class => autowire()->lazy(),
            
            // Workbench
            WorkbenchMediaResolver::class => autowire()->lazy(),
            
            // Scanning
            MissingAltTextScanner::class => autowire()->lazy(),
            
            // Admin
            Admin::class => autowire()->lazy(),
            Menu::class => autowire()->lazy(),
            DashboardPage::class => autowire()->lazy(),
            DashboardMetricsService::class => autowire()->lazy(),
            
            // API
            Api::class => autowire()->lazy(),
            
            // Main Plugin
            ContextAltText::class => autowire()->lazy(),
            
            // Aliases for interface-based injection (future)
            RosterRemote::class => get(RosterClient::class),
        ];
    }
}
```

#### Step 3: Simplify Bootstrap

**Update:** `context-alt-text.php`

```php
<?php
// Replace 300+ lines of manual wiring with:

use ContextAltText\Infrastructure\ContainerConfig;
use Psr\Container\ContainerInterface;

function context_alt_text_container(): ContainerInterface
{
    static $container = null;
    
    if ($container === null) {
        $container = ContainerConfig::build();
    }
    
    return $container;
}

function context_alt_text(): ContextAltText
{
    return context_alt_text_container()->get(ContextAltText::class);
}

// All other factory functions become simple:
function context_alt_text_settings_repository(): SettingsRepository
{
    return context_alt_text_container()->get(SettingsRepository::class);
}
```

**Lines Saved:** ~250 lines in bootstrap file

#### Step 4: Enable Testing Overrides

**Create:** `tests/ContainerTestCase.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Tests;

use DI\Container;
use DI\ContainerBuilder;
use PHPUnit\Framework\TestCase;

abstract class ContainerTestCase extends TestCase
{
    protected Container $container;
    
    protected function setUp(): void
    {
        parent::setUp();
        $this->container = $this->buildTestContainer();
    }
    
    protected function buildTestContainer(): Container
    {
        $builder = new ContainerBuilder();
        $builder->addDefinitions($this->getTestDefinitions());
        return $builder->build();
    }
    
    protected function getTestDefinitions(): array
    {
        return [
            // Override with mocks in test classes
        ];
    }
    
    protected function mock(string $class): object
    {
        $mock = $this->createMock($class);
        $this->container->set($class, $mock);
        return $mock;
    }
}
```

**Usage in tests:**

```php
class RosterServiceTest extends ContainerTestCase
{
    public function testCreateEntry(): void
    {
        // Mock dependencies
        $security = $this->mock(Security::class);
        $rosterClient = $this->mock(RosterClient::class);
        
        // Get service with mocked dependencies
        $service = $this->container->get(RosterService::class);
        
        // Test...
    }
}
```

### Benefits

1. **Drastically Reduced Complexity:** Bootstrap file: 491 → ~50 lines
2. **Better Testability:** Easy to inject mocks
3. **Lazy Loading:** Services only instantiated when needed
4. **Autowiring:** Automatically resolve dependencies
5. **No Circular Dependencies:** Container handles complex graphs
6. **Production Optimization:** Compiled container cached

### Migration Path

**Phase 1 (1-2 days):**
- Install PHP-DI
- Create ContainerConfig
- Update bootstrap to use container
- Verify existing functionality

**Phase 2 (1 day):**
- Update tests to use ContainerTestCase
- Remove manual factory functions

**Phase 3 (Ongoing):**
- Introduce interfaces for better abstraction
- Add configuration profiles (dev/prod/test)

---

## 🔴 CRITICAL IMPROVEMENT 2: Service Provider Architecture

### Current Problem

Bootstrap file mixes multiple concerns:
- Service instantiation
- Configuration loading
- Hook registration
- CLI command registration
- WordPress integration
- Roster snapshot logic (133 lines!)

**Lines 266-398:** Roster snapshot logic embedded in bootstrap

### Recommended Solution: Service Providers

**Pattern:** Laravel-style Service Providers for WordPress

#### Create Service Provider Base

**Create:** `src/Infrastructure/ServiceProvider.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Infrastructure;

use Psr\Container\ContainerInterface;

abstract class ServiceProvider
{
    protected ContainerInterface $container;
    
    public function __construct(ContainerInterface $container)
    {
        $this->container = $container;
    }
    
    /**
     * Register services in the container
     */
    abstract public function register(): void;
    
    /**
     * Bootstrap services (hook registration, etc)
     */
    abstract public function boot(): void;
}
```

#### Create Domain-Specific Providers

**Create:** `src/Recognition/RecognitionServiceProvider.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Infrastructure\ServiceProvider;

final class RecognitionServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        // Container registrations happen in ContainerConfig
        // This is for runtime configuration
    }
    
    public function boot(): void
    {
        // Register WordPress hooks
        add_filter('context_alt_text_recognition_configured', 
            [$this, 'isRecognitionConfigured']
        );
        
        // Register CLI commands if WP_CLI
        if (defined('WP_CLI') && WP_CLI) {
            $this->registerCliCommands();
        }
    }
    
    public function isRecognitionConfigured(): bool
    {
        $settings = $this->container->get(RecognitionSettings::class);
        return $settings->isConfigured();
    }
    
    private function registerCliCommands(): void
    {
        \WP_CLI::add_command('cat-recognition', 
            $this->container->get(RecognitionCli::class)
        );
    }
}
```

**Create:** `src/Roster/RosterServiceProvider.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Roster;

use ContextAltText\Infrastructure\ServiceProvider;

final class RosterServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        // Service registration in container
    }
    
    public function boot(): void
    {
        // Register taxonomy
        $taxonomy = $this->container->get(RosterTaxonomy::class);
        $taxonomy->init();
        
        // Register scheduler
        $scheduler = $this->container->get(RosterSyncScheduler::class);
        $scheduler->register();
        
        // Register remote snapshot filter
        add_filter('context_alt_text_roster_remote_snapshot', 
            [$this, 'provideRosterSnapshot']
        );
        
        // Register CLI commands
        if (defined('WP_CLI') && WP_CLI) {
            \WP_CLI::add_command('cat-roster', 
                $this->container->get(RosterCli::class)
            );
        }
    }
    
    public function provideRosterSnapshot($snapshot): ?array
    {
        if (is_array($snapshot) && $snapshot !== []) {
            return $snapshot;
        }
        
        // Move 133 lines of roster snapshot logic here
        return $this->fetchRosterSnapshot();
    }
    
    private function fetchRosterSnapshot(): ?array
    {
        // Extracted from context-alt-text.php lines 266-398
        $client = $this->container->get(RecognitionClient::class);
        // ... roster fetching logic
    }
}
```

**Create:** `src/Admin/AdminServiceProvider.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Infrastructure\ServiceProvider;

final class AdminServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        // Register admin services
    }
    
    public function boot(): void
    {
        // Bootstrap admin if in admin context
        if (is_admin()) {
            $admin = $this->container->get(Admin::class);
            $admin->bootstrap();
            
            $menu = $this->container->get(Menu::class);
            $menu->init();
        }
    }
}
```

#### Update Bootstrap to Use Providers

**Simplified Bootstrap:**

```php
<?php
// context-alt-text.php

use ContextAltText\Infrastructure\ContainerConfig;
use ContextAltText\Infrastructure\ServiceProvider;

// Build container
$container = ContainerConfig::build();

// Register service providers
$providers = [
    new \ContextAltText\Recognition\RecognitionServiceProvider($container),
    new \ContextAltText\Roster\RosterServiceProvider($container),
    new \ContextAltText\Admin\AdminServiceProvider($container),
    new \ContextAltText\Api\ApiServiceProvider($container),
    new \ContextAltText\Frontend\FrontendServiceProvider($container),
];

// Register all providers
foreach ($providers as $provider) {
    $provider->register();
}

// Boot all providers
add_action('plugins_loaded', function () use ($providers) {
    foreach ($providers as $provider) {
        $provider->boot();
    }
});

// Main plugin accessor
function context_alt_text(): ContextAltText
{
    global $container;
    return $container->get(ContextAltText::class);
}
```

### Benefits

1. **Clear Separation of Concerns:** Each domain manages its own initialization
2. **Easier to Understand:** Related code grouped together
3. **Better Organization:** No more 491-line bootstrap
4. **Easier to Test:** Can test providers independently
5. **Easier to Extend:** New features add new providers

### Migration Estimate

**Effort:** 2-3 days  
**Lines Moved:** ~350 lines from bootstrap to domain providers  
**Final Bootstrap:** ~100 lines (from 491)

---

## 🟡 HIGH IMPROVEMENT 3: Event/Message Bus Architecture

### Current Problem

**Tight Coupling Through Direct Method Calls:**

```php
// recognition-alt-text.php line 163
$recognitionJobService->setRosterObservationManager($rosterObservationManager);
```

This creates circular dependency: RecognitionJobService → RosterObservationManager → RecognitionJobService

**Other Coupling Issues:**
- Admin knows about Recognition, Roster, Workbench
- Api knows about 11 different services
- Hard to add new features without modifying existing classes

### Recommended Solution: Event-Driven Architecture

#### Create Event Bus

**Create:** `src/Infrastructure/EventBus.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Infrastructure;

interface Event
{
    public function getName(): string;
}

interface EventListener
{
    public function handle(Event $event): void;
    public function supports(Event $event): bool;
}

final class EventBus
{
    /** @var EventListener[] */
    private array $listeners = [];
    
    public function subscribe(EventListener $listener): void
    {
        $this->listeners[] = $listener;
    }
    
    public function dispatch(Event $event): void
    {
        foreach ($this->listeners as $listener) {
            if ($listener->supports($event)) {
                $listener->handle($event);
            }
        }
        
        // Also trigger WordPress action
        do_action('context_alt_text_event', $event);
        do_action('context_alt_text_event_' . $event->getName(), $event);
    }
}
```

#### Define Domain Events

**Create:** `src/Recognition/Events/RecognitionJobCompleted.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Recognition\Events;

use ContextAltText\Infrastructure\Event;

final class RecognitionJobCompleted implements Event
{
    public function __construct(
        public readonly string $jobId,
        public readonly array $attachmentIds,
        public readonly array $observations,
        public readonly \DateTimeImmutable $completedAt,
    ) {}
    
    public function getName(): string
    {
        return 'recognition.job.completed';
    }
}
```

**Create:** `src/Roster/Events/RosterEntryCreated.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Roster\Events;

use ContextAltText\Infrastructure\Event;

final class RosterEntryCreated implements Event
{
    public function __construct(
        public readonly string $remoteId,
        public readonly string $label,
        public readonly string $type,
        public readonly \DateTimeImmutable $createdAt,
    ) {}
    
    public function getName(): string
    {
        return 'roster.entry.created';
    }
}
```

#### Create Event Listeners

**Create:** `src/Roster/Listeners/LinkObservationsOnJobComplete.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Roster\Listeners;

use ContextAltText\Infrastructure\Event;
use ContextAltText\Infrastructure\EventListener;
use ContextAltText\Recognition\Events\RecognitionJobCompleted;
use ContextAltText\Roster\RosterObservationManager;

final class LinkObservationsOnJobComplete implements EventListener
{
    public function __construct(
        private RosterObservationManager $observationManager
    ) {}
    
    public function supports(Event $event): bool
    {
        return $event instanceof RecognitionJobCompleted;
    }
    
    public function handle(Event $event): void
    {
        if (!$event instanceof RecognitionJobCompleted) {
            return;
        }
        
        // Link observations to roster entries
        $this->observationManager->linkObservationsForJob($event->jobId);
    }
}
```

#### Update Services to Dispatch Events

**Before (RecognitionJobService):**

```php
// Direct coupling
$this->rosterObservationManager->linkObservations($jobId);
```

**After:**

```php
// Dispatch event instead
$this->eventBus->dispatch(new RecognitionJobCompleted(
    jobId: $jobId,
    attachmentIds: $attachmentIds,
    observations: $observations,
    completedAt: new \DateTimeImmutable(),
));
```

#### Register Listeners in Service Providers

**Update:** `RosterServiceProvider`

```php
public function boot(): void
{
    $eventBus = $this->container->get(EventBus::class);
    
    // Subscribe listeners
    $eventBus->subscribe(
        $this->container->get(LinkObservationsOnJobComplete::class)
    );
}
```

### Benefits

1. **Decoupled:** Services don't know about each other
2. **No Circular Dependencies:** Events flow one direction
3. **Easy to Extend:** Add listeners without modifying core
4. **WordPress Integration:** Events also trigger WP actions
5. **Better Testing:** Test listeners independently
6. **Audit Trail:** Can log all events for debugging

### Use Cases

**Events to Add:**
- `recognition.job.started`
- `recognition.job.completed`
- `recognition.job.failed`
- `roster.entry.created`
- `roster.entry.updated`
- `roster.entry.deleted`
- `roster.sync.started`
- `roster.sync.completed`
- `workbench.item.analyzed`
- `settings.updated`

**Listeners to Create:**
- Link observations on recognition complete
- Invalidate caches on roster changes
- Send analytics events
- Trigger notifications
- Update dashboard metrics

### Migration Estimate

**Effort:** 3-4 days  
**Impact:** Breaks all circular dependencies  
**Lines:** +500 (event infrastructure) - 200 (removed coupling) = Net +300

---

## 🟡 HIGH IMPROVEMENT 4: Repository Pattern Refinement

### Current State

**Good:** Repository pattern already used for data access  
**Issue:** Repositories have mixed responsibilities

**Example:** `RecognitionObservationRepository` (619 lines)
- Data persistence ✅
- Query building ✅
- Data normalization ❌ (should be in separate class)
- Business logic ❌ (lines 537-644: complex roster linking)

### Recommended Refinement

#### Split Concerns

**Keep in Repository:**
- CRUD operations
- Query building
- Database interaction

**Move Out:**
- Normalization → `RecognitionObservationNormalizer`
- Roster linking → `RosterObservationLinker` (domain service)
- Taxonomy operations → `RecognitionTaxonomyManager`

#### Create Normalizer Classes

**Create:** `src/Recognition/RecognitionObservationNormalizer.php`

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Recognition;

final class RecognitionObservationNormalizer
{
    public function normalize(array $payload): array
    {
        // Extract lines 240-380 from RecognitionObservationRepository
        return [
            'observationId' => $this->normalizeObservationId($payload),
            'jobId' => $this->normalizeJobId($payload),
            'attachmentId' => $this->normalizeAttachmentId($payload),
            // ... other fields
        ];
    }
    
    public function normalizeRosterMatch(array $observation): ?array
    {
        // Extract lines 537-644 from RecognitionObservationRepository
    }
    
    private function normalizeObservationId(array $payload): string
    {
        // Extract specific normalization logic
    }
}
```

**Update Repository:**

```php
final class RecognitionObservationRepository
{
    public function __construct(
        private RecognitionObservationNormalizer $normalizer
    ) {}
    
    public function saveObservation(array $payload): string
    {
        // Use normalizer
        $normalized = $this->normalizer->normalize($payload);
        
        // Save to database
        return $this->persist($normalized);
    }
}
```

### Benefits

1. **Single Responsibility:** Each class has one job
2. **Easier to Test:** Test normalization separately from persistence
3. **Better Reusability:** Normalizer can be used outside repository
4. **Clearer Intent:** Repository methods are simpler

### Migration Estimate

**Effort:** 1-2 days  
**Files Affected:** 3 repositories  
**Lines Moved:** ~200 lines per repository

---

## 🟢 MEDIUM IMPROVEMENT 5: Command/Query Separation (CQRS)

### Current State

**Api.php Analysis:**
- 1,509 lines
- Handles both commands (create, update, delete) and queries (list, get)
- Mixed concerns in single class

### Recommended Pattern: CQRS Lite

#### Separate Commands and Queries

**Create:** `src/Application/Commands/`

```php
// src/Application/Commands/CreateRosterEntryCommand.php
final class CreateRosterEntryCommand
{
    public function __construct(
        public readonly string $label,
        public readonly string $type,
        public readonly ?int $avatarId,
        public readonly array $referenceImages,
    ) {}
}

// src/Application/Commands/CreateRosterEntryHandler.php
final class CreateRosterEntryHandler
{
    public function __construct(
        private RosterService $rosterService,
        private EventBus $eventBus,
    ) {}
    
    public function handle(CreateRosterEntryCommand $command): array
    {
        // Validate
        $errors = $this->rosterService->validate([...]);
        if ($errors !== []) {
            throw new ValidationException($errors);
        }
        
        // Execute
        $entry = $this->rosterService->createAndSync([...]);
        
        // Dispatch event
        $this->eventBus->dispatch(new RosterEntryCreated(...));
        
        return $entry;
    }
}
```

**Create:** `src/Application/Queries/`

```php
// src/Application/Queries/ListRosterEntriesQuery.php
final class ListRosterEntriesQuery
{
    public function __construct(
        public readonly ?string $search = null,
        public readonly ?string $type = null,
        public readonly int $page = 1,
        public readonly int $perPage = 20,
    ) {}
}

// src/Application/Queries/ListRosterEntriesHandler.php
final class ListRosterEntriesHandler
{
    public function __construct(
        private RosterService $rosterService,
    ) {}
    
    public function handle(ListRosterEntriesQuery $query): array
    {
        return $this->rosterService->list([
            'search' => $query->search,
            'type' => $query->type,
            'page' => $query->page,
            'per_page' => $query->perPage,
        ]);
    }
}
```

#### Simplify API Layer

**Before (Api.php):**

```php
public function createRosterEntry(WP_REST_Request $request): WP_REST_Response|WP_Error
{
    // 50 lines of validation, business logic, error handling
}
```

**After:**

```php
public function createRosterEntry(WP_REST_Request $request): WP_REST_Response|WP_Error
{
    try {
        $command = new CreateRosterEntryCommand(
            label: $request->get_param('label'),
            type: $request->get_param('type'),
            avatarId: $request->get_param('avatarId'),
            referenceImages: $request->get_param('referenceImages') ?? [],
        );
        
        $result = $this->commandBus->dispatch($command);
        
        return new WP_REST_Response($result, 201);
    } catch (ValidationException $e) {
        return new WP_Error('validation_failed', $e->getMessage(), ['status' => 400]);
    }
}
```

### Benefits

1. **Smaller API Class:** 1,509 → ~500 lines
2. **Testable Business Logic:** Test handlers without WordPress
3. **Clear Intent:** Commands vs Queries obvious
4. **Reusable:** Handlers can be called from CLI, cron, admin
5. **Better Logging:** Log commands/queries for audit

### Migration Estimate

**Effort:** 5-6 days  
**Impact:** Major architectural improvement  
**Files Created:** ~30 command/query handlers

---

## 🟢 MEDIUM IMPROVEMENT 6: Domain Events

### Enhanced Event System

Beyond basic events, add domain-specific events with rich data:

**Create:** `src/Recognition/Domain/Events/`

```php
final class FaceRecognized implements DomainEvent
{
    public function __construct(
        public readonly int $attachmentId,
        public readonly string $observationId,
        public readonly ?string $matchedRosterId,
        public readonly float $confidence,
        public readonly array $boundingBox,
        public readonly \DateTimeImmutable $occurredAt,
    ) {}
    
    public function getAggregateId(): string
    {
        return (string) $this->attachmentId;
    }
    
    public function getEventType(): string
    {
        return 'face_recognized';
    }
}
```

**Use Cases:**
- Analytics tracking
- Audit logs
- Real-time notifications
- Event sourcing (future)
- Integration with external systems

---

## 🟢 LOW IMPROVEMENT 7: Strategic Testing Architecture

### Current Testing Gaps

**Good:**
- PHPUnit tests exist
- Integration tests present
- Contract tests planned

**Missing:**
- Test factories/builders
- Shared test utilities
- Consistent mocking approach
- Performance benchmarks

### Recommended Additions

#### Test Factories

**Create:** `tests/Factories/`

```php
// tests/Factories/RosterEntryFactory.php
final class RosterEntryFactory
{
    public static function make(array $overrides = []): array
    {
        return array_merge([
            'remoteId' => 'test-' . uniqid(),
            'label' => 'Test Entry',
            'type' => 'face',
            'avatar_id' => null,
            'reference_images' => [],
            'status' => 'LOCAL',
            'created_at' => time(),
            'updated_at' => time(),
        ], $overrides);
    }
    
    public static function makeSynced(array $overrides = []): array
    {
        return self::make(array_merge([
            'remoteId' => 'remote-' . uniqid(),
            'status' => 'SYNCED',
        ], $overrides));
    }
}
```

**Usage:**

```php
public function testCreateEntry(): void
{
    $entry = RosterEntryFactory::make([
        'label' => 'John Doe',
    ]);
    
    $result = $this->rosterService->create($entry);
    
    $this->assertEquals('John Doe', $result['label']);
}
```

#### Test Builders

**Create:** `tests/Builders/RecognitionJobBuilder.php`

```php
final class RecognitionJobBuilder
{
    private string $jobId;
    private array $attachmentIds = [];
    private string $status = 'pending';
    
    public function withJobId(string $jobId): self
    {
        $this->jobId = $jobId;
        return $this;
    }
    
    public function withAttachments(array $ids): self
    {
        $this->attachmentIds = $ids;
        return $this;
    }
    
    public function completed(): self
    {
        $this->status = 'complete';
        return $this;
    }
    
    public function build(): array
    {
        return [
            'job_id' => $this->jobId ?? 'job-' . uniqid(),
            'attachment_ids' => $this->attachmentIds,
            'status' => $this->status,
            'created_at' => time(),
        ];
    }
}
```

**Usage:**

```php
public function testJobCompletion(): void
{
    $job = (new RecognitionJobBuilder())
        ->withAttachments([1, 2, 3])
        ->completed()
        ->build();
    
    // Test with fluent builder
}
```

---

## 📊 Implementation Roadmap

### Phase 1: Foundation (Week 1-2)

**Priority:** 🔴 Critical

1. **Dependency Injection Container** (2-3 days)
   - Install PHP-DI
   - Create ContainerConfig
   - Migrate bootstrap file
   - Update 5 key tests

2. **Service Provider Architecture** (2-3 days)
   - Create ServiceProvider base class
   - Create 5 domain providers
   - Move logic from bootstrap
   - Test all providers

**Deliverables:**
- Bootstrap file: 491 → 100 lines
- New files: 7 (container config + 6 providers)
- Tests updated: 10
- Documentation: Container usage guide

---

### Phase 2: Decoupling (Week 3-4)

**Priority:** 🟡 High

3. **Event/Message Bus** (3-4 days)
   - Create EventBus infrastructure
   - Define 10 domain events
   - Create 8 event listeners
   - Update RecognitionJobService to dispatch events
   - Update RosterService to dispatch events
   - Remove circular dependency

4. **Repository Refinement** (2 days)
   - Extract normalizers from 3 repositories
   - Create domain service for roster linking
   - Update repository tests

**Deliverables:**
- No more circular dependencies
- New files: 20 (events + listeners + normalizers)
- Lines moved: ~400
- Documentation: Event system guide

---

### Phase 3: Application Layer (Week 5-7)

**Priority:** 🟢 Medium

5. **CQRS Implementation** (5-6 days)
   - Create Command/Query infrastructure
   - Extract 15 commands
   - Extract 10 queries
   - Create 25 handlers
   - Simplify Api.php
   - Update tests

**Deliverables:**
- Api.php: 1,509 → 500 lines
- New files: 50 (commands/queries/handlers)
- Reusable handlers for CLI/cron
- Documentation: CQRS patterns

---

### Phase 4: Testing Infrastructure (Week 8)

**Priority:** 🟢 Low

6. **Test Factories & Builders** (2-3 days)
   - Create 10 factory classes
   - Create 5 builder classes
   - Update 20 existing tests to use factories
   - Add shared test utilities

7. **Domain Events** (1-2 days)
   - Create rich domain events
   - Add event listeners for analytics
   - Add audit logging

**Deliverables:**
- Tests easier to write and maintain
- Comprehensive test documentation
- Analytics event tracking

---

## 📈 Expected Outcomes

### Metrics

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Bootstrap File Lines | 491 | ~100 | -80% |
| Largest Class (Api.php) | 1,509 | ~500 | -67% |
| Circular Dependencies | 1 | 0 | -100% |
| Manual Dependency Wiring | 100% | 5% | -95% |
| Test Setup Complexity | High | Low | -70% |
| Time to Add Feature | 4h | 2h | -50% |
| New Developer Onboarding | 2 weeks | 1 week | -50% |

### Architectural Quality

**Before:**
- Maintainability: 6/10
- Testability: 6/10
- Extensibility: 5/10
- Complexity: 7/10 (high)
- Coupling: 7/10 (high)

**After:**
- Maintainability: 9/10
- Testability: 9/10
- Extensibility: 9/10
- Complexity: 4/10 (low)
- Coupling: 3/10 (low)

---

## 💡 Quick Wins (Can Do Today)

While planning the strategic improvements, these can be done immediately:

### 1. Add Type Hints to Function Returns

Many functions return `mixed` implicitly. Add explicit return types:

```php
// Before
function context_alt_text()
{
    // ...
}

// After
function context_alt_text(): ContextAltText
{
    // ...
}
```

### 2. Extract Long Functions in Bootstrap

Lines 266-398 (roster snapshot) can be extracted immediately:

```php
// Extract to:
function context_alt_text_fetch_roster_snapshot(): ?array
{
    // Current logic (already exists!)
}
```

### 3. Document Factory Functions

Add PHPDoc to all factory functions explaining purpose and return types.

### 4. Add Interfaces for Key Abstractions

```php
// Create interfaces/
interface RecognitionClientInterface {}
interface RosterServiceInterface {}
interface SettingsRepositoryInterface {}
```

Then type-hint against interfaces instead of concrete classes.

---

## 🎯 Decision Framework

**When to do each improvement:**

### Do Dependency Injection Container if:
- ✅ Adding 3+ new features in next month
- ✅ Onboarding new developers
- ✅ Planning to write comprehensive tests
- ✅ Circular dependencies causing issues

### Do Service Providers if:
- ✅ Bootstrap file becoming unmaintainable
- ✅ Need better domain separation
- ✅ Adding multi-tenancy or configuration profiles

### Do Event Bus if:
- ✅ Have circular dependencies
- ✅ Need integration points for future features
- ✅ Want analytics/auditing infrastructure

### Do CQRS if:
- ✅ Api.php >1,000 lines
- ✅ Need to reuse logic in CLI/cron/admin
- ✅ Want clear read/write separation
- ✅ Planning complex querying or reporting

---

## 📚 References & Resources

### PHP-DI
- **Docs:** https://php-di.org/
- **WordPress Examples:** https://github.com/php-di/demo
- **Performance:** Negligible overhead with compilation

### Event-Driven Architecture
- **Martin Fowler:** https://martinfowler.com/articles/201701-event-driven.html
- **WordPress Hooks:** Already familiar pattern!

### CQRS
- **Martin Fowler:** https://martinfowler.com/bliki/CQRS.html
- **Greg Young:** Event Sourcing talks

### Repository Pattern
- **PHP Version:** https://designpatternsphp.readthedocs.io/en/latest/More/Repository/README.html

---

## ✅ Action Items

**Immediate (This Week):**
- [ ] Review this document with team
- [ ] Decide on Phase 1 start date
- [ ] Install PHP-DI in development branch
- [ ] Create proof-of-concept container config

**Short-term (Next 2 Weeks):**
- [ ] Implement Dependency Injection Container
- [ ] Implement Service Provider Architecture
- [ ] Document new patterns

**Medium-term (Next 2 Months):**
- [ ] Implement Event Bus
- [ ] Refine Repository Pattern
- [ ] Begin CQRS migration

**Long-term (Next Quarter):**
- [ ] Complete CQRS implementation
- [ ] Add comprehensive test infrastructure
- [ ] Implement domain events

---

**Document Status:** Strategic Roadmap - Review and Adapt as Needed  
**Last Updated:** October 17, 2025  
**Owner:** Architecture Team  
**Next Review:** After Phase 1 Completion
