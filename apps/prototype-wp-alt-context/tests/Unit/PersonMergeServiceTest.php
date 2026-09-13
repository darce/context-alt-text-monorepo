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
        return ['id' => $id, 'tenant_id' => $tenant, 'name' => 'Same name', 'tags' => $id === 1 ? '["a"]' : '["b","a"]'];
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
}
