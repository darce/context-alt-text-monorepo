<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/api/class-person-merge-controller.php';

use AltContext\Api\PersonMergeController;
use AltContext\Api\Services\PersonMergeService;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

class PersonMergeControllerTest extends TestCase {
    public function testRejectsInvalidIdsBeforeCallingService(): void {
        $service = $this->createMock(PersonMergeService::class);
        $service->expects($this->never())->method('commit');
        $controller = new PersonMergeController($service);
        foreach ([null, 0, -1, 1.5, true, [], '2x', '999999999999999999999999', 2] as $id) {
            $request = new WP_REST_Request('POST');
            $request->set_param('survivor_id', $id);
            $request->set_param('loser_id', 2);
            $this->assertSame(400, $controller->commit($request)->get_error_data()['status']);
        }
    }

    public function testDispatchUsesServerTenantAndReturnsResponse(): void {
        $service = $this->createMock(PersonMergeService::class);
        $service->expects($this->once())->method('preview')->with(self::currentTenantId(), 1, 2)->willReturn(['conflicts' => []]);
        $request = new WP_REST_Request('POST');
        $request->set_param('survivor_id', '1');
        $request->set_param('loser_id', 2);
        $request->set_param('tenant_id', 'untrusted');
        $this->assertInstanceOf(WP_REST_Response::class, (new PersonMergeController($service))->preview($request));
    }

    public function testRoutesSharePermissionCallback(): void {
        $permission = static fn() => false;
        (new PersonMergeController())->register_routes($permission);
        foreach (['/preview', '', '/undo'] as $index => $suffix) {
            $route = $GLOBALS['__ac_rest_routes'][$index];
            $this->assertSame('acx/v1', $route['namespace']);
            $this->assertSame('/roster/persons/merge' . $suffix, $route['route']);
            $this->assertSame('POST', $route['args']['methods']);
            $this->assertSame($permission, $route['args']['permission_callback']);
        }
    }

    public function testUndoRequiresToken(): void {
        $this->assertSame(400, (new PersonMergeController())->undo(new WP_REST_Request('POST'))->get_error_data()['status']);
    }
}
