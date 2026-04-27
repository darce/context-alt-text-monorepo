<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\MediaDetailController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\MediaDetailController
 */
class MediaDetailControllerTest extends TestCase
{
    public function testGetMediaDetailsReturnsTruncationMetadataWhenRequestExceedsCap(): void
    {
        $ids = array();
        for ($mediaId = 1; $mediaId <= 101; $mediaId++) {
            $ids[] = $mediaId;
        }

        $controller = new MediaDetailController();
        $request = new WP_REST_Request('GET', '/acx/v1/workbench/media/detail');
        $request->set_param('ids[]', $ids);

        $response = $controller->get_media_details($request);

        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();

        $this->assertSame(100, $data['limit']);
        $this->assertSame(101, $data['total']);
        $this->assertTrue($data['truncated']);
        $this->assertCount(100, $data['details_by_media']);
        $this->assertArrayHasKey('100', $data['details_by_media']);
        $this->assertArrayNotHasKey('101', $data['details_by_media']);
    }

    public function testGetMediaDetailsReportsUntruncatedRequestsWithinCap(): void
    {
        $GLOBALS['__ac_attachment_metadata'][7] = array(
            'width' => 640,
            'height' => 480,
        );
        $GLOBALS['__ac_attachment_mimes'][7] = 'image/jpeg';
        $GLOBALS['__ac_post_meta'][7]['acx_xmp_persist_last_result'] = array(
            'status' => 'persisted',
        );

        $controller = new MediaDetailController();
        $request = new WP_REST_Request('GET', '/acx/v1/workbench/media/detail');
        $request->set_param('ids', '7,0,abc');

        $response = $controller->get_media_details($request);

        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();

        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
        $this->assertSame(100, $data['limit']);
        $this->assertSame(640, $data['details_by_media']['7']['dimensions']['width']);
        $this->assertSame('image/jpeg', $data['details_by_media']['7']['mimeType']);
        $this->assertSame(array('status' => 'persisted'), $data['details_by_media']['7']['xmpPersistence']);
    }
}