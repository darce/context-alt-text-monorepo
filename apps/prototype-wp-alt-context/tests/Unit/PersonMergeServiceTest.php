<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/api/services/class-person-merge-service.php';

use AltContext\Api\Services\PersonMergeRepository;
use AltContext\Api\Services\PersonMergeService;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Tests\TestCase;

class PersonMergeServiceTest extends TestCase {
    private function person(int $id, string $tenant = 'tenant'): array {
        return ['id' => $id, 'tenant_id' => $tenant, 'name' => 'Same name', 'person_uuid' => 'person-' . $id, 'normalized_name' => 'same name', 'created_at' => '2026-01-01 00:00:00', 'updated_at' => '2026-01-01 00:00:00', 'local_revision' => 0, 'cluster_count' => 0, 'reference_thumb_path' => null, 'tags' => $id === 1 ? '["a"]' : '["b","a"]'];
    }

    public function testPreviewIsReadOnlyAndUnionsTags(): void {
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturnCallback(fn($id) => $this->person($id));
        $repo->method('clusters')->willReturn([['cluster_uuid' => 'c', 'person_id' => 2, 'tenant_id' => 'tenant']]);
        $repo->expects($this->never())->method('save_undo');
        $repo->expects($this->never())->method('bind');
        $result = (new PersonMergeService($repo))->preview('tenant', 1, 2);
        $this->assertSame(['a', 'b'], $result['tags']);
        $this->assertSame(0, $result['survivor']['cluster_count']);
        $this->assertSame(1, $result['loser']['cluster_count']);
    }

    public function testCommitAndUndoRestoreBindingsAndConsumeToken(): void {
        global $wpdb;
        $people = [1 => $this->person(1), 2 => $this->person(2)];
        $original = $people;
        $clusters = [['cluster_uuid' => 'c', 'person_id' => 2, 'tenant_id' => 'tenant']];
        $records = [];
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturnCallback(static function($id) use (&$people) { return $people[$id] ?? null; });
        $repo->method('clusters')->willReturnCallback(static function() use (&$clusters) { return $clusters; });
        $repo->method('bind')->willReturnCallback(static function($tenant, $cluster, $person) use (&$clusters) { $clusters[0]['person_id'] = $person; });
        $repo->method('set_tags')->willReturnCallback(static function($tenant, $id, $tags) use (&$people) { $people[$id]['tags'] = $tags; });
        $repo->method('remove_person')->willReturnCallback(static function($tenant, $id) use (&$people) { unset($people[$id]); });
        $repo->method('restore_person')->willReturnCallback(static function($row) use (&$people) { $people[$row['id']] = $row; });
        $repo->method('save_undo')->willReturnCallback(static function($tenant, $token, $record) use (&$records) { $records[$tenant][$token] = $record; });
        $repo->method('load_undo')->willReturnCallback(static function($tenant, $token) use (&$records) { return $records[$tenant][$token] ?? null; });
        $repo->method('consume_undo')->willReturnCallback(static function($tenant, $token) use (&$records) { unset($records[$tenant][$token]); });
        $sync = $this->createMock(SyncStateRepositoryInterface::class);
        $sync->expects($this->exactly(2))->method('touch_local_curation_marker')->with('tenant');
        $service = new PersonMergeService($repo, $sync);
        $result = $service->commit('tenant', 1, 2);
        $this->assertSame(['c'], $result['merged_cluster_ids']);
        $this->assertArrayNotHasKey(2, $people);
        $this->assertSame(1, $clusters[0]['person_id']);
        $this->assertSame(409, $service->undo('other', $result['undo_token'])->get_error_data()['status']);
        $mergedTags = $people[1]['tags'];
        $people[1]['tags'] = '["later edit"]';
        $this->assertSame(409, $service->undo('tenant', $result['undo_token'])->get_error_data()['status']);
        $this->assertArrayNotHasKey(2, $people);
        $people[1]['tags'] = $mergedTags;
        $clusters[0]['person_id'] = 3;
        $this->assertSame(409, $service->undo('tenant', $result['undo_token'])->get_error_data()['status']);
        $clusters[0]['person_id'] = 1;
        $this->assertSame(2, $service->undo('tenant', $result['undo_token'])['restored_person_id']);
        $this->assertSame($original, $people);
        $this->assertSame(2, $clusters[0]['person_id']);
        $this->assertSame(409, $service->undo('tenant', $result['undo_token'])->get_error_data()['status']);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testConflictsDoNotWrite(): void {
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturnCallback(fn($id) => $id === 3 ? null : $this->person($id, $id === 2 ? 'other' : 'tenant'));
        $repo->expects($this->never())->method('save_undo');
        $service = new PersonMergeService($repo);
        $this->assertSame(400, $service->preview('tenant', 1, 1)->get_error_data()['status']);
        $this->assertSame(404, $service->commit('tenant', 1, 3)->get_error_data()['status']);
        $this->assertSame(409, $service->commit('tenant', 1, 2)->get_error_data()['status']);
    }

    public function testWriteFailureRollsBack(): void {
        global $wpdb;
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturnCallback(fn($id) => $this->person($id));
        $repo->method('clusters')->willReturn([]);
        $repo->method('save_undo')->willThrowException(new \RuntimeException('write failed'));
        $repo->expects($this->never())->method('remove_person');
        $result = (new PersonMergeService($repo))->commit('tenant', 1, 2);
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    // IDCHIP-1-API-R-02: a failed curation-marker write must roll back the whole commit/undo.
    public function testMarkerWriteFailureRollsBackCommit(): void {
        global $wpdb;
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturnCallback(fn($id) => $this->person($id));
        $repo->method('clusters')->willReturn([]);
        $sync = $this->createMock(SyncStateRepositoryInterface::class);
        $sync->method('touch_local_curation_marker')->willThrowException(new \RuntimeException('marker write failed'));
        $result = (new PersonMergeService($repo, $sync))->commit('tenant', 1, 2);
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    public function testMarkerWriteFailureRollsBackUndo(): void {
        global $wpdb;
        $record = [
            'loser' => $this->person(2),
            'survivor_id' => 1,
            'survivor_tags' => $this->person(1)['tags'],
            'merged_tags' => $this->person(1)['tags'],
            'clusters' => [],
            'expires_at' => time() + PersonMergeService::UNDO_TOKEN_TTL_SECONDS,
        ];
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('load_undo')->willReturn($record);
        $repo->method('person')->willReturnCallback(fn($id) => $id === 1 ? $this->person(1) : null);
        $repo->method('clusters')->willReturn([]);
        $sync = $this->createMock(SyncStateRepositoryInterface::class);
        $sync->method('touch_local_curation_marker')->willThrowException(new \RuntimeException('marker write failed'));
        $result = (new PersonMergeService($repo, $sync))->undo('tenant', '00000001-0000-4000-8000-000000000001');
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertContains('ROLLBACK', $wpdb->queries);
        $this->assertNotContains('COMMIT', $wpdb->queries);
    }

    // IDCHIP-1-API-R-01: expired undo tokens are rejected and deleted.
    public function testExpiredUndoTokenIsRejectedAndDeleted(): void {
        $record = [
            'loser' => $this->person(2),
            'survivor_id' => 1,
            'survivor_tags' => $this->person(1)['tags'],
            'merged_tags' => $this->person(1)['tags'],
            'clusters' => [],
            'expires_at' => time() - 1,
        ];
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('load_undo')->willReturn($record);
        $repo->expects($this->once())->method('consume_undo')->with('tenant', '00000001-0000-4000-8000-000000000001');
        $result = (new PersonMergeService($repo))->undo('tenant', '00000001-0000-4000-8000-000000000001');
        $this->assertSame('person_merge_undo_expired', $result->get_error_code());
        $this->assertSame(409, $result->get_error_data()['status']);
    }

    // IDCHIP-1-API-R-03: malformed/corrupt undo JSON returns a WP_Error, never an uncaught exception.
    public function testMalformedUndoJsonReturnsWpError(): void {
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('load_undo')->willThrowException(new \JsonException('malformed json'));
        $result = (new PersonMergeService($repo))->undo('tenant', '00000001-0000-4000-8000-000000000001');
        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('person_merge_undo_corrupt', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
    }

    public function testUndoRecordWithMissingFieldsIsRejectedAsCorrupt(): void {
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('load_undo')->willReturn(['survivor_id' => 1]);
        $repo->expects($this->once())->method('consume_undo');
        $result = (new PersonMergeService($repo))->undo('tenant', '00000001-0000-4000-8000-000000000001');
        $this->assertSame('person_merge_undo_corrupt', $result->get_error_code());
        $this->assertSame(500, $result->get_error_data()['status']);
    }

    // IDCHIP-1-API-R-05: a retried commit after a lost 200 recovers the original result.
    public function testRetriedCommitRecoversOriginalUndoToken(): void {
        $people = [1 => $this->person(1), 2 => $this->person(2)];
        $records = [];
        $idempotency = [];
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturnCallback(static function ($id) use (&$people) { return $people[$id] ?? null; });
        $repo->method('clusters')->willReturn([]);
        $repo->method('save_undo')->willReturnCallback(static function ($tenant, $token, $record) use (&$records) { $records[$tenant][$token] = $record; });
        $repo->method('load_undo')->willReturnCallback(static function ($tenant, $token) use (&$records) { return $records[$tenant][$token] ?? null; });
        $repo->method('save_merge_idempotency')->willReturnCallback(static function ($tenant, $survivor, $loser, $token) use (&$idempotency) { $idempotency["$tenant:$survivor:$loser"] = $token; });
        $repo->method('load_merge_idempotency')->willReturnCallback(static function ($tenant, $survivor, $loser) use (&$idempotency) { return $idempotency["$tenant:$survivor:$loser"] ?? null; });
        $repo->method('remove_person')->willReturnCallback(static function ($tenant, $id) use (&$people) { unset($people[$id]); });
        $service = new PersonMergeService($repo);
        $first = $service->commit('tenant', 1, 2);
        $this->assertIsArray($first);
        // Simulate the loser already deleted by the original (lost-response) commit.
        $retry = $service->commit('tenant', 1, 2);
        $this->assertIsArray($retry);
        $this->assertSame($first['undo_token'], $retry['undo_token']);
        $this->assertSame($first['merged_cluster_ids'], $retry['merged_cluster_ids']);
    }

    public function testRetriedCommitWithNoIdempotencyRecordStays404(): void {
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturnCallback(fn($id) => $id === 1 ? $this->person(1) : null);
        $repo->method('clusters')->willReturn([]);
        $result = (new PersonMergeService($repo))->commit('tenant', 1, 2);
        $this->assertSame(404, $result->get_error_data()['status']);
    }

    // IDCHIP-1-API-R-04: undo-token syntax must be a real UUID v4, in one shared place.
    public function testUndoTokenSyntaxRejectsNonUuidV4(): void {
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->expects($this->never())->method('load_undo');
        $result = (new PersonMergeService($repo))->undo('tenant', str_repeat('a', 36));
        $this->assertSame('invalid_undo_token', $result->get_error_code());
        $this->assertSame(400, $result->get_error_data()['status']);
    }
    public function testRejectedUndoDeletionRunsAfterRollback(): void {
        global $wpdb;
        $valid = ['loser' => $this->person(2), 'survivor_id' => 1, 'survivor_tags' => null,
            'merged_tags' => '[]', 'clusters' => [], 'expires_at' => time() + 100];
        $cases = [
            [array_replace($valid, ['expires_at' => time()]), 'person_merge_undo_expired'],
            [array_replace($valid, ['survivor_tags' => []]), 'person_merge_undo_corrupt'],
            [array_replace($valid, ['loser' => ['id' => []]]), 'person_merge_undo_corrupt'],
            [array_replace($valid, ['clusters' => [['person_id' => '2']]]), 'person_merge_undo_corrupt'],
            [null, 'person_merge_undo_corrupt'],
            [new \JsonException('bad JSON'), 'person_merge_undo_corrupt'],
            [new \TypeError('bad type'), 'person_merge_undo_corrupt'],
        ];
        foreach ($cases as [$record, $code]) {
            $wpdb->queries = [];
            $repo = $this->createMock(PersonMergeRepository::class);
            if ($record instanceof \Throwable) {
                $repo->method('load_undo')->willThrowException($record);
            } else {
                $repo->method('load_undo')->willReturn($record);
            }
            $repo->method('has_undo')->willReturn(true);
            $repo->expects($this->once())->method('consume_undo')->willReturnCallback(function () use ($wpdb) {
                $this->assertSame('ROLLBACK', end($wpdb->queries));
            });
            $result = (new PersonMergeService($repo))->undo('tenant', '00000001-0000-4000-8000-000000000001');
            $this->assertSame($code, $result->get_error_code());
        }
    }

    public function testMissingSurvivorNeverRecoversCommit(): void {
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturn(null);
        $repo->method('load_merge_idempotency')->willReturn(null);
        $result = (new PersonMergeService($repo))->commit('tenant', 1, 2);
        $this->assertSame('person_not_found', $result->get_error_code());
    }

    public function testRecoveryAndUndoLockOptionBeforePeopleInIdOrder(): void {
        foreach (['commit', 'undo'] as $operation) {
            $locks = [];
            $repo = $this->createMock(PersonMergeRepository::class);
            $record = ['loser' => $this->person(1), 'survivor_id' => 2, 'survivor_tags' => null,
                'merged_tags' => $this->person(2)['tags'], 'clusters' => [], 'expires_at' => time() + 100];
            $repo->method('person')->willReturnCallback(function ($id, $lock) use (&$locks) {
                if ($lock) { $locks[] = $id; }
                return $id === 2 ? $this->person(2) : null;
            });
            $token = '00000001-0000-4000-8000-000000000001';
            $repo->method('load_merge_idempotency')->willReturn($token);
            $repo->method('load_undo')->willReturnCallback(function () use (&$locks, $record) {
                $locks[] = 'undo';
                return $record;
            });
            $repo->method('clusters')->willReturn([]);
            $service = new PersonMergeService($repo, $this->createMock(SyncStateRepositoryInterface::class));
            $result = $operation === 'commit' ? $service->commit('tenant', 2, 1) : $service->undo('tenant', $token);
            $this->assertIsArray($result);
            $this->assertSame(['undo', 1, 2], $locks);
        }
    }

    public function testCorruptTenantIdsAndIncompleteLoserAreConsumedWithoutRestoration(): void {
        $valid = ['loser' => $this->person(2), 'survivor_id' => 1, 'survivor_tags' => null,
            'merged_tags' => '[]', 'clusters' => [], 'expires_at' => time() + 100];
        $cases = [];
        foreach (['1.5', '1e3', '-2', '0', ' 3'] as $id) {
            $record = $valid;
            $record['loser']['id'] = $id;
            $cases[] = $record;
        }
        $record = $valid;
        $record['loser']['tenant_id'] = 'other';
        $cases[] = $record;
        $record = $valid;
        $record['clusters'] = [['cluster_uuid' => 'cluster', 'person_id' => 2, 'tenant_id' => 'other']];
        $cases[] = $record;
        $record = $valid;
        unset($record['loser']['person_uuid']);
        $cases[] = $record;
        foreach ($cases as $record) {
            $repo = $this->createMock(PersonMergeRepository::class);
            $repo->method('load_undo')->willReturn($record);
            $repo->expects($this->never())->method('restore_person');
            $repo->expects($this->once())->method('consume_undo');
            $result = (new PersonMergeService($repo))->undo('tenant', '00000001-0000-4000-8000-000000000001');
            $this->assertSame('person_merge_undo_corrupt', $result->get_error_code());
        }
    }

    public function testApplyTypeErrorRollsBackWithoutConsumingToken(): void {
        global $wpdb;
        $repo = $this->createMock(PersonMergeRepository::class);
        $record = ['loser' => $this->person(2), 'survivor_id' => 1, 'survivor_tags' => null,
            'merged_tags' => $this->person(1)['tags'], 'clusters' => [], 'expires_at' => time() + 100];
        $repo->method('load_undo')->willReturn($record);
        $repo->method('person')->willReturnCallback(fn($id) => $id === 1 ? $this->person(1) : null);
        $repo->method('clusters')->willReturn([]);
        $repo->method('restore_person')->willThrowException(new \TypeError('collaborator failure'));
        $repo->expects($this->never())->method('consume_undo');
        $result = (new PersonMergeService($repo))->undo('tenant', '00000001-0000-4000-8000-000000000001');
        $this->assertSame(500, $result->get_error_data()['status']);
        $this->assertContains('ROLLBACK', $wpdb->queries);
    }

    public function testExpiredCommitCannotBeRecovered(): void {
        $repo = $this->createMock(PersonMergeRepository::class);
        $repo->method('person')->willReturnCallback(fn($id) => $id === 1 ? $this->person(1) : null);
        $repo->method('load_merge_idempotency')->willReturn('00000001-0000-4000-8000-000000000001');
        $repo->method('load_undo')->willReturn(['loser' => $this->person(2), 'survivor_id' => 1,
            'survivor_tags' => null, 'merged_tags' => '[]', 'clusters' => [], 'expires_at' => time()]);
        $result = (new PersonMergeService($repo))->commit('tenant', 1, 2);
        $this->assertSame('person_not_found', $result->get_error_code());
    }

}
