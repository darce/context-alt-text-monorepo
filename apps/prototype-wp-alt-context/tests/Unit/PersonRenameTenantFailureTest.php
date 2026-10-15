<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Api\TenantIdentity;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/** @covers \AltContext\Api\Api */
class PersonRenameTenantFailureTest extends TestCase
{
    private const TENANT = 'ec30f20a-55ad-43dc-890e-e7550dca96e4';
    private const PERSON_UUID = '92e82130-a45a-402a-822d-a0d025ab66c9';
    private const CLUSTERS = [
        '86d6425c-3053-475c-84da-874f169e9b50',
        '7b4cff22-48ad-45aa-80a0-fb7dfef39b36',
    ];

    private object $originalWpdb;
    private PersonRenameFailureWpdb $db;

    protected function setUp(): void
    {
        parent::setUp();
        $this->originalWpdb = $GLOBALS['wpdb'];
        $this->db = new PersonRenameFailureWpdb();
        $GLOBALS['wpdb'] = $this->db;
        $this->setOption(TenantIdentity::OPTION_KEY, self::TENANT);
        $this->setUserCapability('manage_options', true);
        $this->assertSame(self::TENANT, TenantIdentity::resolve()['value']);
        $this->assertNotSame(self::TENANT, md5((string) get_site_url()));

        $this->db->tableRows['wp_acx_persons'] = [[
            'id' => 42,
            'tenant_id' => self::TENANT,
            'person_uuid' => self::PERSON_UUID,
            'name' => 'Gilded Cypress',
            'normalized_name' => 'gilded cypress',
            'tags' => '[]',
            'local_revision' => 3,
        ]];
        $this->db->tableRows['wp_acx_clusters'] = array_map(
            static fn (string $uuid): array => [
                'cluster_uuid' => $uuid,
                'tenant_id' => self::TENANT,
                'person_id' => 42,
                'label' => 'Gilded Cypress',
                'local_revision' => 4,
                'snapshot_version' => 12,
                'curation_state' => 'confirmed',
                'is_user_confirmed' => 1,
                'identity_count' => 3,
            ],
            self::CLUSTERS
        );
    }

    protected function tearDown(): void
    {
        $GLOBALS['wpdb'] = $this->originalWpdb;
        parent::tearDown();
    }

    public function testControlRenameUsesRealWriterAndEnqueuesBothCanonicalLabels(): void
    {
        $this->assertInstanceOf(WP_REST_Response::class, $this->rename());
        $rows = $this->labelRows();
        $this->assertSame(self::CLUSTERS, array_column($rows, 'entity_key'));
        foreach ($rows as $row) {
            $payload = json_decode($row['payload'], true, 512, JSON_THROW_ON_ERROR);
            $this->assertSame('Ellyn Heald', $payload['label']);
            $this->assertSame($row['entity_key'], $payload['cluster_uuid']);
            $this->assertSame(5, (int) $row['local_revision']);
        }
        $this->assertSame(1, $this->db->enumerations);
        $this->assertContains('COMMIT', $this->db->queries);
        $this->assertNotContains('ROLLBACK', $this->db->queries);
    }

    public function testRenameLabelRowsUseCanonicalTenantUuid(): void
    {
        $this->assertInstanceOf(WP_REST_Response::class, $this->rename());
        $rows = $this->labelRows();
        $this->assertCount(2, $rows);
        $this->assertSame(
            [self::TENANT, self::TENANT],
            array_column($rows, 'tenant_id'),
            'F2: every per-cluster rename replay must use TenantIdentity, not the legacy site MD5.'
        );
    }

    public function testRenameLabelRowsAreVisibleThroughCurrentTenantRepository(): void
    {
        $this->assertInstanceOf(WP_REST_Response::class, $this->rename());
        $rows = $this->labelRows();
        $this->assertCount(2, $rows);
        $repository = new OutboxQueryRepository();
        $ids = array_map('intval', array_column($rows, 'id'));
        $this->assertCount(2, $ids);
        $this->assertCount(
            2,
            $repository->find_operations_by_ids($ids, $rows[0]['tenant_id']),
            'Control: the real repository can read these rows under their stored tenant.'
        );
        $this->assertSame([], $repository->find_operations_by_ids($ids, '015e6afe-d82e-4da3-a948-ef022d54afe7'));
        $visible = $repository->find_operations_by_ids($ids, TenantIdentity::resolve()['value']);
        $this->assertCount(2, $visible, 'F2: current-tenant recovery must be able to see both rename replay rows.');
        $this->assertSame(self::CLUSTERS, array_column($visible, 'entity_key'));
    }

    public function testEmptyEnumerationWithSqlErrorFailsAndRollsBackWithoutCommit(): void
    {
        $this->db->enumerationMode = 'empty_error';
        $response = $this->rename();
        $this->assertSame(1, $this->db->enumerations);
        $this->assertSame('Injected bound-cluster enumeration failure', $this->db->last_error);
        $this->assertSame([], $this->labelRows());
        $this->assertSame(
            [true, true, false],
            [
                $response instanceof \WP_Error,
                in_array('ROLLBACK', $this->db->queries, true),
                in_array('COMMIT', $this->db->queries, true),
            ],
            'F3: [] plus last_error is a failed enumeration: WP_Error, ROLLBACK, no COMMIT.'
        );
        $this->assertDatabaseError($response);
    }

    public function testControlCleanEmptyEnumerationIsValidUnboundRename(): void
    {
        $this->db->tableRows['wp_acx_clusters'] = [];
        $this->assertInstanceOf(WP_REST_Response::class, $this->rename());
        $this->assertSame(1, $this->db->enumerations);
        $this->assertSame('', $this->db->last_error);
        $this->assertSame([], $this->labelRows());
        $this->assertContains('COMMIT', $this->db->queries);
        $this->assertNotContains('ROLLBACK', $this->db->queries);
    }

    public function testControlNonArrayEnumerationErrorRollsBack(): void
    {
        $this->db->enumerationMode = 'null_error';
        $this->assertDatabaseError($this->rename());
        $this->assertSame(1, $this->db->enumerations);
        $this->assertSame([], $this->labelRows());
        $this->assertContains('ROLLBACK', $this->db->queries);
        $this->assertNotContains('COMMIT', $this->db->queries);
    }

    public function testControlSecondClusterEnqueueFailureRollsBackAfterFirstInsert(): void
    {
        $this->db->failSecondLabel = true;
        $this->assertDatabaseError($this->rename());
        $this->assertSame(2, $this->db->labelInsertAttempts);
        // WPDBStub records writes but does not emulate persisted transactional rollback.
        $this->assertCount(1, $this->labelRows());
        $this->assertContains('ROLLBACK', $this->db->queries);
        $this->assertNotContains('COMMIT', $this->db->queries);
    }

    private function rename(): WP_REST_Response|\WP_Error
    {
        $request = new WP_REST_Request('PUT', '/acx/v1/roster/persons/42');
        $request->set_param('id', 42);
        $request->set_param('name', 'Ellyn Heald');
        return (new Api())->update_person($request);
    }

    private function labelRows(): array
    {
        return array_values(array_filter(
            $this->db->tableRows['wp_acx_sync_outbox'] ?? [],
            static fn (array $row): bool => 'cluster_label_updated' === $row['operation_type']
        ));
    }

    private function assertDatabaseError(mixed $response): void
    {
        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('acx_db_error', $response->get_error_code());
        $this->assertSame(500, $response->get_error_data()['status']);
    }
}

/** Inject only database outcomes; Api and OutboxWriter remain the real targets. */
class PersonRenameFailureWpdb extends \WPDBStub
{
    public string $enumerationMode = 'normal';
    public int $enumerations = 0;
    public bool $failSecondLabel = false;
    public int $labelInsertAttempts = 0;

    public function get_results($query, $output = OBJECT)
    {
        if (preg_match('/^SELECT cluster_uuid, local_revision FROM `?wp_acx_clusters`? WHERE person_id = /', trim((string) $query))) {
            ++$this->enumerations;
            if ('normal' !== $this->enumerationMode) {
                $this->queries[] = trim((string) $query);
                $this->last_error = 'Injected bound-cluster enumeration failure';
                return 'null_error' === $this->enumerationMode ? null : [];
            }
        }
        return parent::get_results($query, $output);
    }

    public function insert(string $table, array $data, $format = null)
    {
        if ('wp_acx_sync_outbox' === $table && 'cluster_label_updated' === ($data['operation_type'] ?? null)) {
            ++$this->labelInsertAttempts;
            if ($this->failSecondLabel && 2 === $this->labelInsertAttempts) {
                $this->last_error = 'Injected second cluster enqueue failure';
                return false;
            }
        }
        return parent::insert($table, $data, $format);
    }
}
