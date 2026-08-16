

def test_no_missing_data_card_for_a_day_still_in_progress(db_session):
    """A morning with no scores yet is not a failed export — the night may not
    have happened. Warning about it turns every morning into a fault report."""
    from datetime import date

    from backend.src.insights.action_cards import build_action_cards
    from backend.src.models import Sleep

    # Something exists for an earlier day, so `latest` is set.
    db_session.add(Sleep(id="s-14", day=date(2026, 8, 14), score=70))
    db_session.commit()

    today = date(2026, 8, 16)
    cards = build_action_cards(db_session, today, today=today)
    assert not [c for c in cards if c.category == "data"]


def test_missing_data_card_still_fires_for_a_past_day(db_session):
    from datetime import date

    from backend.src.insights.action_cards import build_action_cards
    from backend.src.models import Sleep

    db_session.add(Sleep(id="s-16", day=date(2026, 8, 16), score=70))
    db_session.commit()

    cards = build_action_cards(db_session, date(2026, 8, 15), today=date(2026, 8, 16))
    data_cards = [c for c in cards if c.category == "data"]
    assert len(data_cards) == 1
    assert "sleep" in data_cards[0].reason
