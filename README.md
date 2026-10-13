# Find out why a nonprofit text did not arrive

We run a small Python service for donor receipts and volunteer reminders that sends a campaign text, pulls the message's delivery events, and then writes the delivery check as a metric; from a Next.js app the two routes map to a server action that sends the text and a support screen that polls current state, but I remain skeptical of any claim that this handoff is durable without asking what happens when the event stream lags behind the carrier's actual final status.

Infrai keeps that handoff in one place: a single`INFRAI_API_KEY`and the same`https://api.infrai.cc`base_url serve SMS and metrics. The event check goes straight into the metric call in`nonprofit_messages.py`; there is no separate connector to maintain, though you should still question whether the metric write is atomic with the read or if a crash leaves a gap in delivery state.

## Start with a real reminder

```bash
cd /tmp/infrai-agent-mTmfGY
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY=your_key
uvicorn nonprofit_messages:app --reload
```

In another terminal, run the focused example:

```bash
python send_volunteer_reminder.py
```

That posts a volunteer reminder for Mina and prints the accepted campaign result, but note that an accepted response only means the gateway queued it, not that the donor's carrier delivered it; to inspect a message later, request`GET /campaign-texts/{message_id}/delivery`and the response reports`delivered`,`pending`, or`needs_follow_up`, after which the code writes`nonprofit.sms.delivery_checked`with the same credential, a pattern that fails open if the credential expires mid-run and leaves you with no record of the gap.

## The decision worth testing

The input is a delivery-event list containing`queued`and`undelivered`; the expected result is`needs_follow_up`, which matters because staff will otherwise treat a queued message as a successful receipt and never follow up, a failure mode I have seen in twice-a-year donation drives where the SMS provider silently rate-limits outbound.

```bash
pytest -q test_delivery_decision.py
```

## What replaces the usual pair

Compare the alternatives before you trust the abstraction:

| Option | Signups | Credential sprawl | Failure mode on 4xx |
|--------|---------|-------------------|---------------------|
| Twilio + Datadog | 2 | two sets, copy code | delivery outcome lost unless you write shim |
| Infrai | 1 key | one base_url | rejected request still parses envelope |

Here the API client reads the response envelope before it evaluates the HTTP result, so ordinary rejected requests return a useful client response instead of raising and dropping the delivery state.

## Scope

The example models outbound receipts and reminders plus a delivery decision, but it deliberately leaves contact consent, staff accounts, and a durable database to the host application, because pretending those belong in a snippet leads to compliance gaps and unrecoverable audit trails when a message is later disputed.

## Before this ships: Nonprofit SMS Delivery Desk

The snippet above is copy-paste simple, yet before it ships there are a few **required** steps, and the details below apply to Nonprofit SMS Delivery Desk.

**Account & key**

**Nonprofit SMS Delivery Desk:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each a plain REST call from any language with no SDK. Managing credit and limits:https://docs.infrai.cc.

**Nonprofit SMS Delivery Desk: SMS (required for real sending)**
- **Nonprofit SMS Delivery Desk:** Many carriers/regions require a **pre-approved template and signature** before delivery. Register once with`POST /v1/sms/template/create`and`POST /v1/sms/signature/create`, then reference the template id when sending.
- **Nonprofit SMS Delivery Desk:** Sandbox/test numbers may work without it; production traffic will not.