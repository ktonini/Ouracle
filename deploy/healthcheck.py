"""Container healthcheck: token-authenticated ping against the local API.

Invoked by the quadlet's HealthCmd (a script avoids shell-quoting layers:
systemd unit -> podman -> sh -c would otherwise each eat quotes).
"""

import os
import sys
import urllib.request

port = os.environ.get("OURACLE_MOBILE_PORT", "8037")
token = os.environ.get("OURACLE_MOBILE_TOKEN", "")
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/api/mobile/ping",
    headers={"Authorization": f"Bearer {token}"},
)
try:
    urllib.request.urlopen(request, timeout=4)
except Exception as e:  # noqa: BLE001 - any failure means unhealthy
    print(f"unhealthy: {e}", file=sys.stderr)
    sys.exit(1)
