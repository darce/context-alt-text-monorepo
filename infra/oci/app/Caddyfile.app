# BEGIN APP_PORTAL_VHOST
# Public customer portal on the existing OCI edge. TLS is Caddy ACME.
# Static SPA at /; backend portal API only under /portal.
# Admin, webhooks, health, and description-service APIs stay off this vhost.
app.altcontext.com {
	header Strict-Transport-Security "max-age=31536000"

	@admin path /admin /admin/*
	respond @admin 404

	@unrelated path /recognition /recognition/* /roster /roster/* /scene /scene/* /billing/webhooks /billing/webhooks/* /health /health/* /ready /metrics /docs /openapi.json /redoc /x /x/*
	respond @unrelated 404

	@portal path /portal /portal/*
	handle @portal {
		reverse_proxy __APP_UPSTREAM__
	}

	handle {
		header Content-Security-Policy "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; script-src 'self' https://clerk.altcontext.com https://challenges.cloudflare.com https://*.protect.clerk.com; connect-src 'self' https://clerk.altcontext.com https://*.protect.clerk.com:*; img-src 'self' https://img.clerk.com; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; frame-src https://challenges.cloudflare.com https://*.protect.clerk.com; form-action 'self' https://clerk.altcontext.com;"
		root * __APP_FRONTEND_ROOT__
		encode gzip
		try_files {path} /index.html
		file_server
	}
}
# END APP_PORTAL_VHOST
