/**
 * Admin JavaScript for Context Alt Text plugin
 */

(function ($) {
    'use strict';

    $(document).ready(function () {
        hydrateDashboardStatus();
    });

    function hydrateDashboardStatus() {
        if (typeof window.ContextAltTextAdmin === 'undefined') {
            return;
        }

        const data = window.ContextAltTextAdmin.data || {};
        const statusLine = $('.cat-status-line');

        if (!statusLine.length) {
            return;
        }

        if (typeof data.missing === 'number') {
            statusLine.text(`We found ${data.missing} images missing alt text`);
        }
    }
})(jQuery);
