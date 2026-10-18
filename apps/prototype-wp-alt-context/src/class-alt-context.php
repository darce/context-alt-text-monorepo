<?php

declare(strict_types=1);

namespace AltContext;

require_once __DIR__ . '/public/class-public-demo-shortcode.php';
require_once __DIR__ . '/public/class-public-guide-route.php';

use AltContext\Admin\Admin;
use AltContext\Admin\AttachmentFields;
use AltContext\Api\Api;
use AltContext\Admin\Menu;
use AltContext\Media\AttachmentXmpMetricsPersistor;
use AltContext\Support\LifecycleManager;
use AltContext\PublicSite\PublicDemoShortcode;
use AltContext\PublicSite\PublicGuideRoute;

class AltContext {

	private Admin $admin;
	private Api $api;
	private Menu $menu;
	private LifecycleManager $lifecycle;
	private ?AttachmentXmpMetricsPersistor $attachmentXmpMetricsPersistor;

	public function __construct(
		Admin $admin,
		Api $api,
		Menu $menu,
		LifecycleManager $lifecycle,
		?AttachmentXmpMetricsPersistor $attachment_xmp_metrics_persistor = null
	) {
		$this->admin     = $admin;
		$this->api       = $api;
		$this->menu      = $menu;
		$this->lifecycle = $lifecycle;
		$this->attachmentXmpMetricsPersistor = $attachment_xmp_metrics_persistor;
	}

	public function init(): void {
		$this->admin->init();
		( new AttachmentFields() )->init();
		$this->menu->init();
		$this->api->init();
		( new PublicDemoShortcode() )->init();
		( new PublicGuideRoute() )->init();
		if ( $this->attachmentXmpMetricsPersistor instanceof AttachmentXmpMetricsPersistor ) {
			$this->attachmentXmpMetricsPersistor->init();
		}
	}

	public function lifecycle(): LifecycleManager {
		return $this->lifecycle;
	}
}
