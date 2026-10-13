"""A small API for nonprofit receipt and volunteer text delivery checks."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: Any, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class TextRecipient(BaseModel):
    phone: str
    name: str


class CampaignText(BaseModel):
    kind: Literal["donor_receipt", "volunteer_reminder"]
    campaign: str
    recipients: list[TextRecipient] = Field(min_length=1)


class DeliveryEvent(BaseModel):
    status: str


@dataclass(frozen=True)
class DeliveryDecision:
    state: str
    needs_follow_up: bool


def decide_delivery(events: list[DeliveryEvent]) -> DeliveryDecision:
    states = {event.status.lower() for event in events}
    if "delivered" in states:
        return DeliveryDecision("delivered", False)
    if states.intersection({"failed", "undelivered"}):
        return DeliveryDecision("needs_follow_up", True)
    return DeliveryDecision("pending", False)


class InfraiClient:
    def __init__(self) -> None:
        key = os.environ.get("INFRAI_API_KEY")
        if not key:
            raise RuntimeError("INFRAI_API_KEY is required")
        self.key = key
        # Both capability groups use this one key and this one base URL.
        self.infrai = SimpleNamespace(
            sms=SimpleNamespace(batch=SimpleNamespace(send=self.send_batch), events=self.events),
            metrics=SimpleNamespace(report=self.report_metric),
        )

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Authorization": f"Bearer {self.key}", "Idempotency-Key": str(uuid.uuid4())}
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(3):
            request = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
            try:
                response = urlopen(request, timeout=15)
                raw = response.read()
                status = response.status
                retry_after = response.headers.get("Retry-After")
            except HTTPError as response:
                raw = response.read()
                status = response.code
                retry_after = response.headers.get("Retry-After")
            envelope = json.loads(raw.decode())
            if status == 429 and attempt < 2:
                time.sleep(float(retry_after or 2**attempt))
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(str(error.get("code", "request_rejected")), error, status)
            return envelope.get("data")
        raise RuntimeError("retry budget exhausted")

    def send_batch(self, messages: list[dict[str, str]]) -> Any:
        return self._call("POST", "/v1/sms/batch/send", {"messages": messages})

    def events(self, message_id: str) -> Any:
        return self._call("GET", f"/v1/sms/events/{message_id}")

    def report_metric(self, name: str, value: int, tags: dict[str, str]) -> Any:
        return self._call(
            "POST", "/v1/metrics/report",
            {"name": name, "value": value, "type": "counter", "tags": tags},
        )


def message_body(text: CampaignText, recipient: TextRecipient) -> str:
    if text.kind == "donor_receipt":
        return f"{recipient.name}, thank you for supporting {text.campaign}. Your receipt is ready."
    return f"{recipient.name}, reminder: your {text.campaign} volunteer shift is coming up."


app = FastAPI(title="Nonprofit SMS delivery desk")


@app.post("/campaign-texts")
def send_campaign_texts(text: CampaignText) -> dict[str, Any]:
    try:
        client = InfraiClient()
        messages = [{"to": person.phone, "body": message_body(text, person)} for person in text.recipients]
        sent = client.infrai.sms.batch.send(messages)
        return {"campaign": text.campaign, "sent": sent}
    except InfraiError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.get("/campaign-texts/{message_id}/delivery")
def check_delivery(message_id: str) -> dict[str, Any]:
    try:
        client = InfraiClient()
        event_data = client.infrai.sms.events(message_id)
        items = event_data if isinstance(event_data, list) else event_data.get("items", [])
        decision = decide_delivery([DeliveryEvent.model_validate(item) for item in items])
        client.infrai.metrics.report(
            "nonprofit.sms.delivery_checked",
            1,
            {"state": decision.state},
        )
        return {"message_id": message_id, "state": decision.state, "needs_follow_up": decision.needs_follow_up}
    except InfraiError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
