# BEGIN APP_PORTAL_VHOST
# Public customer portal on the existing OCI edge. TLS is Caddy ACME.
# Static SPA at /; backend portal API only under /portal.
# Admin, webhooks, health, and description-service APIs stay off this vhost.
app.altcontext.com {
	@admin path /admin /admin/*
	respond @admin 404

	@unrelated path /recognition /recognition/* /roster /roster/* /scene /scene/* /billing/webhooks /billing/webhooks/* /health /health/* /ready /metrics /docs /openapi.json /redoc /x /x/*
	respond @unrelated 404

	handle /portal* {
		reverse_proxy __APP_UPSTREAM__
	}

	handle {
		root * __APP_FRONTEND_ROOT__
		encode gzip
		try_files {path} /index.html
		file_server
	}
}
# END APP_PORTAL_VHOST
