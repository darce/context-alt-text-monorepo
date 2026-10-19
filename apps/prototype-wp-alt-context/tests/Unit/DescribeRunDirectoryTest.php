<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/** @covers \AltContext\Api\DescribeController */
class DescribeRunDirectoryTest extends TestCase
{
    public function testListsOnlyAcceptedRunsForRequestedMediaNewestFirstWithoutRemoteCompute(): void
    {
        $older = '11111111-1111-4111-8111-111111111111';
        $newer = '22222222-2222-4222-8222-222222222222';
        $foreign = '33333333-3333-4333-8333-333333333333';
        $this->setOption('acx_describe_run_media_ids_index', [$older => 100, $newer => 200, $foreign => 300]);
        $this->setOption('acx_describe_run_media_ids_' . $older, ['media_ids' => [22, 23]]);
        $this->setOption('acx_describe_run_media_ids_' . $newer, ['media_ids' => [22]]);
        $this->setOption('acx_describe_run_media_ids_' . $foreign, ['media_ids' => [99]]);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [22]);
        $request->set_param('limit', 1);
        $data = (new DescribeController())->list_describe_runs_for_media($request)->get_data();
        self::assertSame(2, $data['total']);
        self::assertSame([['run_id' => $newer, 'created_at' => 200, 'media_ids' => [22]]], $data['items']);
        self::assertSame(1, $data['next_offset']);
        $request->set_param('offset', 1);
        $data = (new DescribeController())->list_describe_runs_for_media($request)->get_data();
        self::assertSame($older, $data['items'][0]['run_id']);
        self::assertNull($data['next_offset']);
    }

    public function testDoesNotTrustIndexEntriesWithoutDurableMediaMembership(): void
    {
        $run = '11111111-1111-4111-8111-111111111111';
        $this->setOption('acx_describe_run_media_ids_index', [$run => 100]);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [22]);
        $data = (new DescribeController())->list_describe_runs_for_media($request)->get_data();
        self::assertSame([], $data['items']);
    }
}
