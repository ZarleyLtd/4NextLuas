from src.common.stations import (
    build_station, find_station, match_platforms, parse_direction,
    bad_direction_speech, normalize_name, options_speech,
    split_station_and_direction,
)


def dundrum():
    return build_station("Dundrum", [
        {"stop_id": "N", "stop_code": "1", "headsigns": ["Broombridge", "Parnell"]},
        {"stop_id": "S", "stop_code": "2", "headsigns": ["Brides Glen", "Sandyford"]},
    ])


def belgard():
    return build_station("Belgard", [
        {"stop_id": "W", "stop_code": "1", "headsigns": ["Saggart", "Tallaght"]},
        {"stop_id": "E", "stop_code": "2", "headsigns": ["Connolly", "The Point", "Belgard"]},
    ])


def stephens_green():
    return build_station("St. Stephen's Green", [
        {"stop_id": "S", "stop_code": "1", "headsigns": ["Brides Glen", "Sandyford"]},
        {"stop_id": "N", "stop_code": "2", "headsigns": ["Broombridge", "Parnell"]},
    ])


def broombridge():
    return build_station("Broombridge", [
        {"stop_id": "ARR", "stop_code": "1", "headsigns": ["Broombridge"]},
        {"stop_id": "OUT", "stop_code": "2", "headsigns": ["Brides Glen", "Sandyford"]},
    ])


def test_dundrum_cardinals_and_citybound():
    st = dundrum()
    north = next(p for p in st.platforms if p.stop_id == "N")
    south = next(p for p in st.platforms if p.stop_id == "S")
    assert north.cardinals == ["northbound"]
    assert south.cardinals == ["southbound"]
    assert north.citybound is True
    assert south.citybound is False
    assert st.city_centre is False


def test_match_direction_phrases():
    st = dundrum()
    assert match_platforms(st, "northbound")[0].stop_id == "N"
    assert match_platforms(st, parse_direction("south"))[0].stop_id == "S"
    assert match_platforms(st, parse_direction("towards the city"))[0].stop_id == "N"
    assert match_platforms(st, parse_direction("towards Broombridge"))[0].stop_id == "N"
    assert match_platforms(st, parse_direction("towards Brides Glen"))[0].stop_id == "S"
    assert match_platforms(st, parse_direction("to Brides Glen"))[0].stop_id == "S"
    assert match_platforms(st, "eastbound") == []


def test_city_centre_towards_the_city_is_empty():
    st = stephens_green()
    assert st.city_centre is True
    assert match_platforms(st, "city") == []
    assert "ambiguous" in bad_direction_speech(st, "city").lower()
    assert match_platforms(st, "northbound")[0].stop_id == "N"


def test_belgard_westbound_covers_both_branches():
    st = belgard()
    west = match_platforms(st, "westbound")
    assert len(west) == 1 and west[0].stop_id == "W"
    assert match_platforms(st, parse_direction("towards Tallaght"))[0].stop_id == "W"
    assert match_platforms(st, parse_direction("towards Saggart"))[0].stop_id == "W"
    assert match_platforms(st, "eastbound")[0].stop_id == "E"
    assert match_platforms(st, "city")[0].stop_id == "E"


def test_terminus_arrival_filtered():
    st = broombridge()
    usable = st.usable_platforms()
    assert [p.stop_id for p in usable] == ["OUT"]
    assert match_platforms(st, None)[0].stop_id == "OUT"


def test_find_station_aliases():
    catalog = [dundrum(), stephens_green(), belgard()]
    assert find_station(catalog, "Dundrum").name == "Dundrum"
    assert find_station(catalog, "stephens green").name == "St. Stephen's Green"
    assert find_station(catalog, "St Stephen's Green").name == "St. Stephen's Green"
    assert find_station(catalog, "nowhere") is None


def test_parse_direction():
    assert parse_direction("northbound") == "northbound"
    assert parse_direction("south bound") == "southbound"
    assert parse_direction("going south") == "southbound"
    assert parse_direction("going north") == "northbound"
    assert parse_direction("heading south") == "southbound"
    assert parse_direction("going southbound") == "southbound"
    assert parse_direction("towards Broombridge") == "broombridge"
    assert parse_direction("to Brides Glen") == "brides glen"
    assert parse_direction("towards Brides Glen") == "brides glen"
    assert parse_direction("the city") == "city"
    assert parse_direction("") is None


def test_split_station_glued_direction():
    assert split_station_and_direction("Dundrum southbound", None) == ("Dundrum", "southbound")
    assert split_station_and_direction("Dundrum south bound", None) == ("Dundrum", "southbound")
    assert split_station_and_direction("Dundrum going south", None) == ("Dundrum", "southbound")
    assert split_station_and_direction("Dundrum going north", None) == ("Dundrum", "northbound")
    assert split_station_and_direction("Dundrum towards Brides Glen", None) == ("Dundrum", "brides glen")
    assert split_station_and_direction("Dundrum to Brides Glen", None) == ("Dundrum", "brides glen")
    assert split_station_and_direction("Dundrum southbound", "northbound") == ("Dundrum", "northbound")
    assert split_station_and_direction("Dundrum", "southbound") == ("Dundrum", "southbound")
    assert split_station_and_direction("Dundrum", None) == ("Dundrum", None)


def test_options_speech_lists_both():
    text = options_speech(dundrum())
    assert "northbound" in text and "southbound" in text


def test_normalize_strips_luas_words():
    assert normalize_name("Dundrum Luas") == "dundrum"
    assert normalize_name("O'Connell Upr.") == "o connell upper"
