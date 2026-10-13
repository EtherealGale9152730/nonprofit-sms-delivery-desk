from nonprofit_messages import DeliveryEvent, decide_delivery


def test_failure_event_marks_a_donor_text_for_follow_up() -> None:
    decision = decide_delivery([DeliveryEvent(status="queued"), DeliveryEvent(status="undelivered")])

    assert decision.state == "needs_follow_up"
    assert decision.needs_follow_up is True
