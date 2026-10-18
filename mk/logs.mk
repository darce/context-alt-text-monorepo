# =============================================================================
# Recognition service remote log targets
# =============================================================================
# Tail or grep docker logs on the OCI host for a specific environment.
#
# Variables (all optional):
#   SERVICE  api | worker | postgres   (default: api)
#   FOLLOW   1 to stream (-f), unset for snapshot   (default: unset)
#   SINCE    docker --since value, e.g. 5m, 1h, 2025-04-26T00:00:00  (default: 10m)
#   GREP     pattern piped through grep -E on the host
#   TAIL     line count for snapshot reads          (default: 200)
#   OCI_HOST OCI_USER  override remote host
#
# Examples:
#   make logs-dev                                  # last 10m of acx-dev-api-1
#   make logs-dev SERVICE=worker FOLLOW=1          # stream worker logs
#   make logs-dev GREP='ERROR|Traceback'           # filter snapshot
#   make logs-prod SERVICE=worker SINCE=1h TAIL=500

OCI_HOST ?= 129.213.40.111
OCI_USER ?= ubuntu
SERVICE  ?= api
SINCE    ?= 10m
TAIL     ?= 200

# Compose the remote command. With FOLLOW=1, drop --tail so docker streams from
# now; without, snapshot the last $(TAIL) lines bounded by --since.
ifeq ($(FOLLOW),1)
LOGS_DOCKER_FLAGS := -f --since $(SINCE)
else
LOGS_DOCKER_FLAGS := --since $(SINCE) --tail $(TAIL)
endif

ifdef GREP
LOGS_PIPE := 2>&1 | grep -E --color=never -- '$(GREP)'
else
LOGS_PIPE := 2>&1
endif

.PHONY: logs-help logs-dev logs-staging logs-prod

logs-help:
	@echo "Remote log targets (docker logs on OCI host):"
	@echo "  make logs-dev      [SERVICE=api|worker|postgres] [FOLLOW=1] [SINCE=10m] [GREP=pattern] [TAIL=200]"
	@echo "  make logs-staging  ... (same flags)"
	@echo "  make logs-prod     ... (same flags)"
	@echo ""
	@echo "Examples:"
	@echo "  make logs-dev                                  # last 10m of acx-dev-api-1"
	@echo "  make logs-dev SERVICE=worker FOLLOW=1          # stream worker logs"
	@echo "  make logs-dev GREP='ERROR|Traceback'           # filter snapshot"
	@echo "  make logs-prod SERVICE=worker SINCE=1h TAIL=500"

logs-dev:
	@ssh $(OCI_USER)@$(OCI_HOST) "docker logs $(LOGS_DOCKER_FLAGS) acx-dev-$(SERVICE)-1 $(LOGS_PIPE)"

logs-staging:
	@ssh $(OCI_USER)@$(OCI_HOST) "docker logs $(LOGS_DOCKER_FLAGS) acx-staging-$(SERVICE)-1 $(LOGS_PIPE)"

logs-prod:
	@ssh $(OCI_USER)@$(OCI_HOST) "docker logs $(LOGS_DOCKER_FLAGS) acx-prod-$(SERVICE)-1 $(LOGS_PIPE)"
