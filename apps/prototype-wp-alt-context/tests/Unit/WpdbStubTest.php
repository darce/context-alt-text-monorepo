<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * @coversNothing
 */
class WpdbStubTest extends TestCase
{
    public function testInsertAssignsDistinctIdsOnSuccessiveInserts(): void
    {
        global $wpdb;

        $wpdb->insert('wp_acx_persons', array(
            'name' => 'First',
            'normalized_name' => 'first',
        ));
        $firstId = $wpdb->insert_id;

        $wpdb->insert('wp_acx_persons', array(
            'name' => 'Second',
            'normalized_name' => 'second',
        ));
        $secondId = $wpdb->insert_id;

        $this->assertGreaterThan(0, $firstId);
        $this->assertGreaterThan(0, $secondId);
        $this->assertNotSame($firstId, $secondId, 'successive inserts must not reuse insert_id');
        $this->assertSame($firstId, $wpdb->tableRows['wp_acx_persons'][0]['id']);
        $this->assertSame($secondId, $wpdb->tableRows['wp_acx_persons'][1]['id']);
    }
}
