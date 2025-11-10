<?php

declare(strict_types=1);

namespace AltContext;

use AltContext\Admin\Admin;
use AltContext\Api\Api;
use AltContext\Admin\Menu;
use AltContext\Frontend\Frontend;
use AltContext\Support\LifecycleManager;

class AltContext {

	private Admin $admin;
	private Frontend $frontend;
	private Api $api;
	private Menu $menu;
	private LifecycleManager $lifecycle;

	public function __construct(
		Admin $admin,
		Frontend $frontend,
		Api $api,
		Menu $menu,
		LifecycleManager $lifecycle
	) {
		$this->admin     = $admin;
		$this->frontend  = $frontend;
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
