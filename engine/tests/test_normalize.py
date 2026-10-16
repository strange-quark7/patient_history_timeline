from medtimeline import normalize as n


def test_parse_date_day_first_and_ambiguity():
    assert n.parse_date("12/01/2024") == ("2024-01-12", True)
    assert n.parse_date("25.12.23") == ("2023-12-25", False)
    assert n.parse_date("no date") == (None, False)


def test_parse_date_us_style_fallback_is_flagged():
    assert n.parse_date("04/25/2024") == ("2024-04-25", True)


def test_expand_frequency():
    assert n.expand_frequency("BD") == "twice daily"
    assert n.expand_frequency("1-0-1") == "morning and night"
    assert n.expand_frequency("1/2-0-1") == "morning (1/2) and night"
    assert n.expand_frequency("as told") is None


def test_duration_days():
    assert n.duration_days("x 5d") == 5
    assert n.duration_days("2 weeks") == 14
    assert n.duration_days("1 month") == 30
    assert n.duration_days(None) is None


def test_drug_key_links_variants():
    assert n.normalize_drug_key("Tab. Pan 40") == n.normalize_drug_key("PAN 40mg") == "pan"
