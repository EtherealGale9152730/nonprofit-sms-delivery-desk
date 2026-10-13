"""Send one realistic reminder through the local service."""

import json
from urllib.request import Request, urlopen


payload = {
    "kind": "volunteer_reminder",
    "campaign": "Saturday pantry packing",
    "recipients": [{"phone": "+15551234567", "name": "Mina"}],
}
request = Request(
    "http://127.0.0.1:8000/campaign-texts",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request) as response:
    print(response.read().decode())
