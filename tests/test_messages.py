from reach_agent import messages
from tests.helpers import mon, thu, tue


def test_when_uses_relative_days_when_natural():
    assert messages.when(mon(18), now=mon(14)) == "hoje às 18:00"
    assert messages.when(tue(9), now=mon(14)) == "amanhã às 09:00"
    assert messages.when(thu(10), now=mon(14)) == "quinta, 24/09, às 10:00"


def test_offer_numbers_the_options_in_order():
    text = messages.offer_slots([tue(18, 30), thu(18)], now=mon(18))
    assert "1) amanhã às 18:30\n2) quinta, 24/09, às 18:00" in text
