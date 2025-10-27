<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Infrastructure\Database;

use ContextAltText\Infrastructure\Database\UnknownFaceTableInstaller;
use ContextAltText\Tests\TestCase;

final class UnknownFaceTableInstallerTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        /** @var \WPDBStub $wpdb */
        $wpdb = $GLOBALS['wpdb'];
        $wpdb->reset();
    }

    public function test_installs_table_with_expected_schema(): void
    {
        /** @var \WPDBStub $wpdb */
        $wpdb = $GLOBALS['wpdb'];
        $installer = new UnknownFaceTableInstaller($wpdb);

        $installer->install();

        $this->assertNotEmpty($wpdb->queries, 'Expected installer to run at least one SQL query.');
        $sql = $wpdb->queries[0];

        $this->assertStringContainsString('CREATE TABLE IF NOT EXISTS wp_cat_unknown_faces', $sql);
        $this->assertStringContainsString('attachment_id BIGINT(20) UNSIGNED NOT NULL', $sql);
        $this->assertStringContainsString('bbox_json LONGTEXT NOT NULL', $sql);
        $this->assertStringContainsString('embedding_id VARCHAR(255)', $sql);
        $this->assertStringContainsString('cluster_id VARCHAR(255)', $sql);
        $this->assertStringContainsString('detected_at DATETIME NOT NULL', $sql);
        $this->assertStringContainsString('resolved_at DATETIME NULL', $sql);
        $this->assertStringContainsString('roster_id VARCHAR(255) NULL', $sql);
        $this->assertStringContainsString('KEY attachment_id (attachment_id)', $sql);
        $this->assertStringContainsString('KEY cluster_id (cluster_id)', $sql);
        $this->assertStringContainsString('KEY resolved_at (resolved_at)', $sql);
    }

    public function test_install_is_idempotent(): void
    {
        /** @var \WPDBStub $wpdb */
        $wpdb = $GLOBALS['wpdb'];
        $installer = new UnknownFaceTableInstaller($wpdb);

        $installer->install();
        $installer->install();

        $this->assertCount(2, $wpdb->queries, 'Installer should run the CREATE TABLE statement on each call.');
        $this->assertSame($wpdb->queries[0], $wpdb->queries[1]);
    }
}
