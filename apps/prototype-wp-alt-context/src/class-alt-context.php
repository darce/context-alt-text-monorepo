<?php

declare(strict_types=1);

namespace AltContext;

use AltContext\Admin\Admin;
use AltContext\Api\Api;
use AltContext\Admin\Menu;
use AltContext\Support\LifecycleManager;

class AltContext {

	private Admin $admin;
	private Api $api;
	private Menu $menu;
	private LifecycleManager $lifecycle;

	public function __construct(
		Admin $admin,
		Api $api,
		Menu $menu,
		LifecycleManager $lifecycle
	) {
		$this->admin     = $admin;
		$this->api       = $api;
		$this->menu      = $menu;
		$this->lifecycle = $lifecycle;
	}

	public function init(): void {
		$this->admin->init();
		$this->menu->init();
		$this->api->init();
	}

	public function lifecycle(): LifecycleManager {
		return $this->lifecycle;
	}
}
