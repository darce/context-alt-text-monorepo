<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Admin;

use ContextAltText\Admin\Admin;
use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Roster\RosterSyncScheduler;
use ContextAltText\Roster\RosterObservationManager;
use ContextAltText\Recognition\RecognitionObservationRepository;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Security\Security;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Shared\Config\SettingsRepository;
use ContextAltText\Workbench\WorkbenchMediaResolver;
use ContextAltText\Tests\Roster\Support\FakeRosterClient;
use PHPUnit\Framework\TestCase;

use const JSON_THROW_ON_ERROR;
use function array_key_exists;
use function define;
use function defined;
use function file_exists;
use function file_put_contents;
use function is_dir;
use function json_encode;
use function mkdir;
use function unlink;

final class AdminAssetEnqueueTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_scripts'] = [];
        $GLOBALS['__cat_styles'] = [];
        $GLOBALS['__cat_localized_scripts'] = [];
    }

    public function test_enqueue_script_uses_dev_server_when_environment_is_development(): void
    {
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'development';
        if (!defined('CONTEXT_ALT_TEXT_VITE_DEV_SERVER')) {
            define('CONTEXT_ALT_TEXT_VITE_DEV_SERVER', 'http://dev.local:5173');
        }

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return [
                    'total' => 10,
                    'with_alt' => 5,
                    'missing' => 5,
                ];
            }
        };

        $metrics = $this->fakeMetricsService($scanner);
        [$rosterService, $rosterScheduler, $rosterObservationManager] = $this->buildRosterDependencies();
        $admin = new Admin(
            $scanner,
            $metrics,
            $this->fakeFeatureFlags(),
            new WorkbenchMediaResolver(),
            $rosterService,
            $rosterScheduler,
            new SettingsRepository(),
            $rosterObservationManager
        );
        $admin->enqueue_script(Admin::DASHBOARD_HOOK);

        self::assertArrayHasKey('context-alt-text-admin-entry', $GLOBALS['__cat_scripts']);
        $entry = $GLOBALS['__cat_scripts']['context-alt-text-admin-entry'];
        self::assertStringStartsWith('http://dev.local:5173/js/admin/main.tsx', (string) $entry['src']);
        self::assertArrayHasKey('context-alt-text-admin-dev', $GLOBALS['__cat_scripts']);

        $localized = $GLOBALS['__cat_localized_scripts']['context-alt-text-admin-entry']['ContextAltTextAdmin'] ?? null;
        self::assertIsArray($localized);
        self::assertSame('dashboard', $localized['page'] ?? null);
        self::assertArrayHasKey('config', $localized);
        $config = $localized['config'];
        self::assertIsArray($config);
        self::assertSame('nonce-wp_rest', $config['restNonce']);
        self::assertIsArray($config['endpoints'] ?? null);
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/dashboard/coverage',
            $config['endpoints']['coverage'] ?? null
        );
        self::assertArrayHasKey('workbenchMedia', $config['endpoints']);
        self::assertSame('', $config['endpoints']['workbenchMedia']);
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/roster',
            $config['endpoints']['rosterEntries'] ?? null
        );
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/roster/sync',
            $config['endpoints']['rosterSync'] ?? null
        );
        self::assertArrayHasKey('featureFlags', $config);
        self::assertArrayHasKey('rosterEnabled', $config['featureFlags']);
        self::assertFalse($config['featureFlags']['workbenchEnabled']);
        self::assertTrue($config['featureFlags']['abilitiesEnabled']);
        self::assertTrue($config['featureFlags']['rosterEnabled']);
        self::assertArrayHasKey('dashboard', $localized['data']);
        self::assertArrayHasKey('workbench', $localized['data']);
        self::assertArrayHasKey('roster', $localized['data']);
    }

    public function test_enqueue_script_loads_manifest_assets_in_production(): void
    {
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'production';
        if (!defined('CONTEXT_ALT_TEXT_VITE_DEV_SERVER')) {
            define('CONTEXT_ALT_TEXT_VITE_DEV_SERVER', 'http://dev.local:5173');
        }

        $manifestDir = CONTEXT_ALT_TEXT_PLUGIN_DIR . 'public/assets/dist/.vite';
        if (!is_dir($manifestDir)) {
            mkdir($manifestDir, 0777, true);
        }

        $manifestPath = $manifestDir . '/manifest.json';
        file_put_contents($manifestPath, json_encode([
            'js/admin/main.tsx' => [
                'file' => 'js/admin.js',
                'css' => ['css/admin.css'],
            ],
        ], JSON_THROW_ON_ERROR));

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return [
                    'total' => 0,
                    'with_alt' => 0,
                    'missing' => 0,
                ];
            }
        };

        $metrics = $this->fakeMetricsService($scanner);
        [$rosterService, $rosterScheduler, $rosterObservationManager] = $this->buildRosterDependencies();
        $admin = new Admin(
            $scanner,
            $metrics,
            $this->fakeFeatureFlags(),
            new WorkbenchMediaResolver(),
            $rosterService,
            $rosterScheduler,
            new SettingsRepository(),
            $rosterObservationManager
        );
        $admin->enqueue_script(Admin::DASHBOARD_HOOK);

        self::assertArrayHasKey('context-alt-text-admin', $GLOBALS['__cat_scripts']);
        $script = $GLOBALS['__cat_scripts']['context-alt-text-admin'];
        self::assertStringContainsString('public/assets/dist/js/admin.js', (string) $script['src']);

        self::assertTrue(
            array_key_exists('context-alt-text-admin-0', $GLOBALS['__cat_styles']),
            'CSS from manifest should be enqueued'
        );

        $localized = $GLOBALS['__cat_localized_scripts']['context-alt-text-admin']['ContextAltTextAdmin'] ?? null;
        self::assertIsArray($localized);
        self::assertSame('dashboard', $localized['page'] ?? null);
        self::assertArrayHasKey('config', $localized);
        $config = $localized['config'];
        self::assertIsArray($config);
        self::assertSame('nonce-wp_rest', $config['restNonce']);
        self::assertIsArray($config['endpoints'] ?? null);
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/dashboard/coverage',
            $config['endpoints']['coverage'] ?? null
        );
        self::assertArrayHasKey('workbenchMedia', $config['endpoints']);
        self::assertSame('', $config['endpoints']['workbenchMedia']);
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/roster',
            $config['endpoints']['rosterEntries'] ?? null
        );
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/roster/sync',
            $config['endpoints']['rosterSync'] ?? null
        );
        self::assertArrayHasKey('featureFlags', $config);
        self::assertArrayHasKey('rosterEnabled', $config['featureFlags']);
        self::assertFalse($config['featureFlags']['workbenchEnabled']);
        self::assertTrue($config['featureFlags']['abilitiesEnabled']);
        self::assertTrue($config['featureFlags']['rosterEnabled']);
        self::assertArrayHasKey('workbench', $localized['data']);
        self::assertArrayHasKey('roster', $localized['data']);

        if (file_exists($manifestPath)) {
            unlink($manifestPath);
        }
    }

    public function test_force_module_type_adds_attribute_when_missing(): void
    {
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'production';
        if (!defined('CONTEXT_ALT_TEXT_VITE_DEV_SERVER')) {
            define('CONTEXT_ALT_TEXT_VITE_DEV_SERVER', 'http://dev.local:5173');
        }

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return [
                    'total' => 0,
                    'with_alt' => 0,
                    'missing' => 0,
                ];
            }
        };

        $metrics = $this->fakeMetricsService($scanner);
        [$rosterService, $rosterScheduler, $rosterObservationManager] = $this->buildRosterDependencies();
        $admin = new Admin(
            $scanner,
            $metrics,
            $this->fakeFeatureFlags(),
            new WorkbenchMediaResolver(),
            $rosterService,
            $rosterScheduler,
            new SettingsRepository(),
            $rosterObservationManager
        );

        $admin->bootstrap();

        $tag = '<script src="foo.js"></script>';
        $filtered = apply_filters('script_loader_tag', $tag, 'context-alt-text-admin', 'foo.js');
        self::assertSame('<script type="module" src="foo.js"></script>', $filtered);

        $other = apply_filters('script_loader_tag', $tag, 'some-other-handle', 'foo.js');
        self::assertSame($tag, $other);
    }

    public function test_enqueue_script_runs_for_workbench_page(): void
    {
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'development';
        if (!defined('CONTEXT_ALT_TEXT_VITE_DEV_SERVER')) {
            define('CONTEXT_ALT_TEXT_VITE_DEV_SERVER', 'http://dev.local:5173');
        }

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return [
                    'total' => 3,
                    'with_alt' => 1,
                    'missing' => 2,
                ];
            }
        };

        $metrics = $this->fakeMetricsService($scanner);
        [$rosterService, $rosterScheduler, $rosterObservationManager] = $this->buildRosterDependencies();
        $admin = new Admin(
            $scanner,
            $metrics,
            $this->fakeFeatureFlags(),
            new WorkbenchMediaResolver(),
            $rosterService,
            $rosterScheduler,
            new SettingsRepository(),
            $rosterObservationManager
        );

        $_GET['page'] = 'context-alt-text-workbench';

        $admin->enqueue_script('context-alt-text-dashboard_page_context-alt-text-workbench');

        self::assertArrayHasKey('context-alt-text-admin-entry', $GLOBALS['__cat_scripts']);
        $localized = $GLOBALS['__cat_localized_scripts']['context-alt-text-admin-entry']['ContextAltTextAdmin'] ?? null;
        self::assertIsArray($localized);
        self::assertSame('workbench', $localized['page'] ?? null);
        $config = $localized['config'] ?? null;
        self::assertIsArray($config);
        self::assertArrayHasKey('featureFlags', $config);
        self::assertArrayHasKey('rosterEnabled', $config['featureFlags']);
        self::assertTrue($config['featureFlags']['workbenchEnabled']);
        self::assertTrue($config['featureFlags']['abilitiesEnabled']);
        self::assertTrue($config['featureFlags']['rosterEnabled']);
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/workbench/media',
            $config['endpoints']['workbenchMedia'] ?? null
        );
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/roster',
            $config['endpoints']['rosterEntries'] ?? null
        );

        unset($_GET['page']);
    }

    public function test_enqueue_script_runs_for_roster_page(): void
    {
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'development';
        if (!defined('CONTEXT_ALT_TEXT_VITE_DEV_SERVER')) {
            define('CONTEXT_ALT_TEXT_VITE_DEV_SERVER', 'http://dev.local:5173');
        }

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return [
                    'total' => 0,
                    'with_alt' => 0,
                    'missing' => 0,
                ];
            }
        };

        $metrics = $this->fakeMetricsService($scanner);
        [$rosterService, $rosterScheduler, $rosterObservationManager] = $this->buildRosterDependencies();
        $admin = new Admin(
            $scanner,
            $metrics,
            $this->fakeFeatureFlags(),
            new WorkbenchMediaResolver(),
            $rosterService,
            $rosterScheduler,
            new SettingsRepository(),
            $rosterObservationManager
        );

        $_GET['page'] = 'context-alt-text-roster';

        $admin->enqueue_script('context-alt-text-dashboard_page_context-alt-text-roster');

        self::assertArrayHasKey('context-alt-text-admin-entry', $GLOBALS['__cat_scripts']);
        $localized = $GLOBALS['__cat_localized_scripts']['context-alt-text-admin-entry']['ContextAltTextAdmin'] ?? null;
        self::assertIsArray($localized);
        self::assertSame('roster', $localized['page'] ?? null);
        $config = $localized['config'] ?? null;
        self::assertIsArray($config);
        self::assertSame(
            'http://example.test/wp-json/context-alt-text/v1/roster',
            $config['endpoints']['rosterEntries'] ?? null
        );
        self::assertArrayHasKey('featureFlags', $config);
        self::assertArrayHasKey('rosterEnabled', $config['featureFlags']);
        self::assertTrue($config['featureFlags']['abilitiesEnabled']);
        self::assertTrue($config['featureFlags']['rosterEnabled']);
        $data = $localized['data'] ?? [];
        self::assertIsArray($data['roster'] ?? null);

        unset($_GET['page']);
    }

    /**
     * @return array{RosterService,RosterSyncScheduler,RosterObservationManager}
     */
    private function buildRosterDependencies(): array
    {
        $service = new RosterService(new Security(), new FakeRosterClient());

        /** @var RecognitionObservationRepository&\PHPUnit\Framework\MockObject\MockObject $observationRepository */
        $observationRepository = $this->createMock(RecognitionObservationRepository::class);
        $observationRepository->method('findAttachmentIdsNeedingReview')->willReturn([]);
        $observationRepository->method('getMany')->willReturn([]);
        $observationRepository->method('updateObservation')->willReturn([]);

        /** @var RecognitionJobService&\PHPUnit\Framework\MockObject\MockObject $jobService */
        $jobService = $this->createMock(RecognitionJobService::class);
        $jobService->method('submit')->willReturn([]);

        $manager = new RosterObservationManager($observationRepository, $jobService);

        return [$service, new RosterSyncScheduler($service), $manager];
    }

    private function fakeFeatureFlags(): FeatureFlags
    {
        return new class extends FeatureFlags {
            public function coverageTrendEnabled(): bool
            {
                return false;
            }

            public function workbenchEnabled(): bool
            {
                return false;
            }

            public function workbenchRecognitionEnabled(): bool
            {
                return false;
            }

            public function workbenchBulkAIEnabled(): bool
            {
                return false;
            }

            public function rosterUiEnabled(): bool
            {
                return true;
            }

            public function abilitiesEnabled(): bool
            {
                return true;
            }
        };
    }

    private function fakeMetricsService(MissingAltTextScanner $scanner): DashboardMetricsService
    {
        return new class($scanner) extends DashboardMetricsService {
            public function __construct(private MissingAltTextScanner $overrideScanner)
            {
                parent::__construct($overrideScanner);
            }

            public function getHeroStatus(): array
            {
                return [
                    'state' => 'ready',
                    'message' => 'Test',
                    'cta_label' => 'Go',
                    'cta_url' => '#',
                ];
            }

            public function getCoverageCard(): array
            {
                return [
                    'total' => 10,
                    'with_alt' => 5,
                    'missing' => 5,
                    'coverage_percent' => 50,
                ];
            }

            public function getLatestActivityCard(): array
            {
                return [
                    'last_recognition' => null,
                    'last_alt_text_generation' => null,
                    'last_roster_sync' => null,
                ];
            }

            public function getRecognitionInsightsCard(): array
            {
                return [
                    'pending_faces' => 0,
                    'pending_brands' => 0,
                    'unresolved_matches' => 0,
                    'roster_pending' => 0,
                    'roster_conflicts' => 0,
                    'roster_total' => 0,
                    'last_roster_sync_human' => null,
                    'last_roster_sync_at' => null,
                ];
            }

            public function getAutomationPipelineCard(): array
            {
                return [
                    'queued' => 0,
                    'running' => 0,
                    'completed' => 0,
                    'next_run' => null,
                ];
            }

            public function getFooterActions(): array
            {
                return [
                    ['label' => 'Test action', 'url' => '#'],
                ];
            }

            public function getFooterStatusText(): string
            {
                return 'Test status';
            }
        };
    }
}
