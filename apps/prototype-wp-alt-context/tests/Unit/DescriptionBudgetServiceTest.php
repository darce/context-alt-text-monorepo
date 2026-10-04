<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionBudgetService;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Services\DescriptionBudgetService
 * @covers \AltContext\Sovereign\Repositories\DescriptionUsageRepository
 */
class DescriptionBudgetServiceTest extends TestCase
{
    public function testRecordsSuccessfulAndFailedUsageAttempts(): void
    {
        $service = new DescriptionBudgetService();

        $service->record_success(
            media_id: 42,
            adapter: 'local_cpu',
            provider: 'local',
            duration_ms: 1200,
            cached: false,
            write_status: 'updated'
        );
        $service->record_error(
            media_id: 43,
            adapter: 'hosted',
            provider: 'service',
            error_code: 'provider_timeout',
            error_message: 'Provider timed out',
            retryable: true,
            source: 'backend'
        );

        $summary = $service->usage_summary();
        $this->assertSame(2, $summary['attempts']);
        $this->assertSame(1, $summary['successes']);
        $this->assertSame(1, $summary['failures']);
        $this->assertSame(0.0, $summary['cost_total']);

        $errors = $service->recent_errors();
        $this->assertSame('provider_timeout', $errors[0]['error_code']);
        $this->assertSame('Provider timed out', $errors[0]['error_message']);
        $this->assertTrue($errors[0]['retryable']);
        $this->assertSame('backend', $errors[0]['source']);
    }

    public function testUsageRowsPersistAcrossRepositoryInstances(): void
    {
        $first = new DescriptionBudgetService();
        $first->record_error(
            media_id: 71,
            adapter: 'hosted',
            provider: 'service',
            error_code: 'provider_timeout',
            error_message: 'Provider timed out',
            retryable: true,
            source: 'backend'
        );

        $second = new DescriptionBudgetService();

        $summary = $second->usage_summary();
        $this->assertSame(1, $summary['attempts']);
        $this->assertSame(1, $summary['failures']);
        $this->assertSame('provider_timeout', $second->recent_errors()[0]['error_code']);
    }

    public function testBudgetGateDeniesWhenAttemptLimitExceeded(): void
    {
        $this->setOption('acx_description_budget_max_attempts', 1);

        $service = new DescriptionBudgetService();
        $service->record_success(
            media_id: 42,
            adapter: 'local_cpu',
            provider: 'local',
            duration_ms: 1200,
            cached: false,
            write_status: 'updated'
        );

        $gate = $service->check_budget();

        $this->assertFalse($gate['allowed']);
        $this->assertSame('description_budget_attempt_limit_exceeded', $gate['code']);
        $this->assertSame(1, $gate['limit']);
        $this->assertSame(1, $gate['used']);
    }

    public function testBudgetGateUsesFiniteDefaultAttemptLimit(): void
    {
        $gate = (new DescriptionBudgetService())->check_budget();

        $this->assertTrue($gate['allowed']);
        $this->assertSame(DescriptionBudgetService::DEFAULT_MAX_ATTEMPTS, $gate['limit']);
        $this->assertSame(0, $gate['used']);
    }

    public function testRequestRateLimitBoundsSpendRoutesPerUser(): void
    {
        $GLOBALS['wpdb']->mockVar = '1';
        $service = new DescriptionBudgetService();

        for ($attempt = 0; $attempt < 30; ++$attempt) {
            $this->assertTrue($service->check_request_rate_limit(17)['allowed']);
        }

        $denied = $service->check_request_rate_limit(17);
        $this->assertFalse($denied['allowed']);
        $this->assertSame('recognition_rate_limit_exceeded', $denied['code']);
        $this->assertSame(30, $denied['limit']);
        $this->assertGreaterThanOrEqual(1, $denied['retry_after']);
        $this->assertTrue($service->check_request_rate_limit(18)['allowed']);
    }
}
