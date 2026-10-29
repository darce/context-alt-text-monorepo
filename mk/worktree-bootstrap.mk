# WorkBay worktree bootstrap policy for task-start. The gitignored overlay
# recipe (Makefile.d/lifecycle.mk) forwards this value inside single quotes as
# WORKBAY_WORKTREE_BOOTSTRAP_CMD, so it must never contain a single quote.
# Included before Makefile.d/*.mk so this ?= wins over the overlay empty
# default; LIFECYCLE_WORKTREE_BOOTSTRAP= on the command line disables it and an
# environment value overrides it. task-start runs it with cwd = new worktree.
LIFECYCLE_WORKTREE_BOOTSTRAP ?= "$(PYTHON)" "$(ROOT_MAKEFILE_DIR)/scripts/workstate/bootstrap_worktree.py" --worktree .
