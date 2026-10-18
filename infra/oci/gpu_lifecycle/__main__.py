"""python -m infra.oci.gpu_lifecycle → idle reaper entrypoint."""

from infra.oci.gpu_lifecycle.reaper import main

if __name__ == "__main__":
    raise SystemExit(main())
