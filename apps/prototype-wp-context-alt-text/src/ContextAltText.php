<?php

declare(strict_types=1);

namespace CAT;

use CAT\Admin\Admin;
use CAT\Frontend\Frontend;
use CAT\Api\Api;
use CAT\Admin\Menu;

class ContextAltText
{
    private Admin $admin;
    private Frontend $frontend;
    private Api $api;
    private Menu $menu;

    public function __construct(
        Admin $admin,
        Frontend $frontend,
        Api $api,
        Menu $menu
    ) {
        $this->admin = $admin;
        $this->frontend = $frontend;
        $this->api = $api;
        $this->menu = $menu;
    }

    public function init(): void
    {
        $this->admin->init();
        $this->menu->init();
    }
}
?>