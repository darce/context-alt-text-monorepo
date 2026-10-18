<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\IdentityMemberDeletionService;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\IdentityMemberDeletionService
 */
class IdentityMemberDeletionServiceTest extends TestCase
{
    private IdentityMemberDeletionService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->service = new IdentityMemberDeletionService('wp_acx_identity_members', 'wp_acx_clusters');
    }

    public function testDeleteMemberScopesByTenant(): void
    {
        $this->service->delete_member('identity-delete-service', 'tenant-delete-service');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('DELETE m FROM `wp_acx_identity_members` m', $sql);
        $this->assertStringContainsString("'identity-delete-service'", $sql);
        $this->assertStringContainsString("'tenant-delete-service'", $sql);
    }
}
