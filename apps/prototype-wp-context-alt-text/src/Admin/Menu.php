<?php
declare(strict_types=1);

namespace CAT\Admin;

class Menu
{
    private DashboardPage $dashboardPage;
    //private WorkbenchPage $workbenchPage;

    public function __construct(
        DashboardPage $dashboardPage,
        //WorkbenchPage $workbenchPage
    ) {
        $this->dashboardPage = $dashboardPage;
        //$this->workbenchPage = $workbenchPage;
    }
    public function init(): void
    {
        add_action('admin_menu', [$this, 'menu']);
    }   

    public function menu(): void
    {
        add_menu_page(
            __('Context Alt Text', 'cat'),
            __('Context Alt Text', 'cat'),
            'manage_options',
            'cat-dashboard',
            [$this, 'admin_page'],
            'dashicons-universal-access-alt',
            60
        );
    }
    public function admin_page(): void
    {
        $this->dashboardPage->render();
    }
}
?>
