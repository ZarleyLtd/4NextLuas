"""Luas station names, direction aliases, and platform matching.

GTFS gives two stop_ids per station (one platform each) and trip headsigns that
include short-workings (Sandyford, Red Cow, Belgard) as well as termini. Direction
phrases are curated aliases on top of those headsigns — not live GPS.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Headsigns that imply a compass direction. Short-workings are omitted here so
# "Sandyford" can appear on both Green Line platforms without flipping the cardinal.
GREEN_NORTH_HEADS = frozenset({"Broombridge", "Parnell"})
GREEN_SOUTH_HEADS = frozenset({"Brides Glen"})
RED_EAST_HEADS = frozenset({"Connolly", "The Point"})
RED_WEST_HEADS = frozenset({"Tallaght", "Saggart", "Red Cow", "Heuston"})

# "Towards the city" is ambiguous at these GTFS stop_name values.
CITY_CENTRE = frozenset({
    "Abbey St.", "Busáras", "Dawson", "Dominick", "Jervis", "Marlborough",
    "O'Connell - GPO", "O'Connell Upr.", "Parnell", "St. Stephen's Green",
    "Trinity", "Westmoreland",
})

# Green Line north of the city: citybound = southbound.
GREEN_NORTH_OF_CITY = frozenset({
    "Broombridge", "Cabra", "Phibsborough", "Grangegorman", "Broadstone",
})

# Red Line docklands / Connolly: citybound = westbound (back towards Abbey Street).
RED_CITYBOUND_WEST = frozenset({
    "Connolly", "George's Dock", "Mayor Square", "Spencer Dock", "The Point",
})

# Spoken names Alexa should prefer, mapped to the GTFS stop_name.
SPOKEN_TO_GTFS = {
    "Abbey Street": "Abbey St.",
    "Busaras": "Busáras",
    "O'Connell GPO": "O'Connell - GPO",
    "O'Connell Upper": "O'Connell Upr.",
    "St Stephen's Green": "St. Stephen's Green",
    "Citywest Campus": "Citywest",
    "Ballyogan Wood": "Ballyogan",
    "Leopardstown Valley": "Leopardstown",
    "Tallaght Hospital": "Hospital",
    "Broadstone DIT": "Broadstone",
}

# Extra phrases that should resolve to a GTFS stop_name after normalisation.
EXTRA_ALIASES = {
    "abbey": "Abbey St.",
    "abbey st": "Abbey St.",
    "the gpo": "O'Connell - GPO",
    "oconnell street": "O'Connell - GPO",
    "o connell street": "O'Connell - GPO",
    "o connell": "O'Connell - GPO",
    "oconnell": "O'Connell - GPO",
    "stephens green": "St. Stephen's Green",
    "stephen s green": "St. Stephen's Green",
    "st stephens green": "St. Stephen's Green",
    "the green": "St. Stephen's Green",
    "bus aras": "Busáras",
    "busaras": "Busáras",
    "the point": "The Point",
    "point village": "The Point",
    "three arena": "The Point",
    "3arena": "The Point",
    "citywest": "Citywest",
    "ballyogan": "Ballyogan",
    "leopardstown": "Leopardstown",
    "the gallops": "The Gallops",
    "hospital": "Hospital",
    "the hospital": "Hospital",
    "tallaght hospital": "Hospital",
    "james": "James's",
    "jamess": "James's",
    "st jamess": "James's",
    "james s": "James's",
    "parnell square": "Parnell",
    "mayors square": "Mayor Square",
    "nci": "Mayor Square",
    "heuston station": "Heuston",
    "connolly station": "Connolly",
    "the red cow": "Red Cow",
    "bridesglen": "Brides Glen",
    "bride s glen": "Brides Glen",
}

CARDINALS = {
    "northbound": "northbound", "north": "northbound", "nb": "northbound",
    "southbound": "southbound", "south": "southbound", "sb": "southbound",
    "eastbound": "eastbound", "east": "eastbound", "eb": "eastbound",
    "westbound": "westbound", "west": "westbound", "wb": "westbound",
}

CITY_PHRASES = frozenset({
    "the city", "city", "city centre", "city center", "into town", "town",
    "into the city", "towards the city", "toward the city",
})

_TOWARDS_PREFIX = re.compile(r"^(?:towards|toward|to|going|heading)\s+", re.I)


def normalize_name(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.casefold().replace("&", " and ").replace("'", " ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\b(luas|stop|station|tram)\b", " ", t)
    t = re.sub(r"\b(st|saint)\b", "st", t)
    t = re.sub(r"\b(upr|uppr)\b", "upper", t)
    return " ".join(t.split())


def classify_headsigns(headsigns: set[str]) -> list[str]:
    """Return cardinals that apply to this platform, in a stable order."""
    heads = {h.strip() for h in headsigns if h and h.strip()}
    out: list[str] = []
    # Brides Glen wins over Parnell when both appear (the Parnell stop itself).
    if heads & GREEN_SOUTH_HEADS:
        out.append("southbound")
    if (heads & GREEN_NORTH_HEADS) and "southbound" not in out:
        out.append("northbound")
    if heads & RED_EAST_HEADS:
        out.append("eastbound")
    if (heads & RED_WEST_HEADS) and "eastbound" not in out:
        out.append("westbound")
    return out


def is_city_centre(gtfs_name: str) -> bool:
    return gtfs_name in CITY_CENTRE


def is_citybound(gtfs_name: str, cardinals: list[str]) -> bool:
    if is_city_centre(gtfs_name):
        return False
    if gtfs_name in GREEN_NORTH_OF_CITY:
        return "southbound" in cardinals
    if gtfs_name in RED_CITYBOUND_WEST:
        return "westbound" in cardinals
    if "northbound" in cardinals:
        return True
    if "eastbound" in cardinals:
        return True
    return False


def is_terminus_arrival(gtfs_name: str, headsigns: list[str]) -> bool:
    heads = {h.strip() for h in headsigns if h.strip()}
    return bool(heads) and heads <= {gtfs_name}


def spoken_name(gtfs_name: str) -> str:
    for spoken, gtfs in SPOKEN_TO_GTFS.items():
        if gtfs == gtfs_name:
            return spoken
    return gtfs_name.replace("St.", "St")


def platform_towards(headsigns: list[str]) -> list[str]:
    """Headsigns worth saying as 'towards X', termini first."""
    priority = (
        "Broombridge", "Brides Glen", "Tallaght", "Saggart", "Connolly",
        "The Point", "Parnell", "Sandyford", "Heuston", "Red Cow", "Belgard",
        "Kingswood",
    )
    seen: list[str] = []
    heads = [h.strip() for h in headsigns if h and h.strip()]
    for name in priority:
        if name in heads and name not in seen:
            seen.append(name)
    for h in heads:
        if h not in seen:
            seen.append(h)
    return seen


def brief_platform(cardinals: list[str], towards: list[str]) -> str:
    if cardinals and towards:
        return f"{cardinals[0]} towards {towards[0]}"
    if cardinals:
        return cardinals[0]
    if towards:
        return "towards " + towards[0]
    return "that platform"


@dataclass
class Platform:
    stop_id: str
    stop_code: str
    stop_name: str
    headsigns: list[str]
    cardinals: list[str]
    citybound: bool
    towards: list[str]
    arrival_only: bool = False

    def as_dict(self) -> dict:
        return {
            "stop_id": self.stop_id,
            "stop_code": self.stop_code,
            "stop_name": self.stop_name,
            "headsigns": self.headsigns,
            "cardinals": self.cardinals,
            "citybound": self.citybound,
            "towards": self.towards,
            "arrival_only": self.arrival_only,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Platform":
        return cls(
            stop_id=d["stop_id"], stop_code=d.get("stop_code") or "",
            stop_name=d["stop_name"], headsigns=list(d.get("headsigns") or []),
            cardinals=list(d.get("cardinals") or []),
            citybound=bool(d.get("citybound")),
            towards=list(d.get("towards") or []),
            arrival_only=bool(d.get("arrival_only")),
        )

    @property
    def label(self) -> str:
        spoken = spoken_name(self.stop_name)
        extra = brief_platform(self.cardinals, self.towards)
        if extra == "that platform":
            return spoken
        return f"{spoken}, {extra}"


@dataclass
class Station:
    name: str
    spoken: str
    city_centre: bool
    platforms: list[Platform] = field(default_factory=list)

    def usable_platforms(self) -> list[Platform]:
        usable = [p for p in self.platforms if not p.arrival_only]
        return usable or list(self.platforms)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "spoken": self.spoken,
            "city_centre": self.city_centre,
            "platforms": [p.as_dict() for p in self.platforms],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Station":
        return cls(
            name=d["name"], spoken=d.get("spoken") or spoken_name(d["name"]),
            city_centre=bool(d.get("city_centre")),
            platforms=[Platform.from_dict(p) for p in d.get("platforms") or []],
        )


def build_station(gtfs_name: str, raw_platforms: list[dict]) -> Station:
    platforms = []
    for raw in raw_platforms:
        heads = sorted({h.strip() for h in raw.get("headsigns") or [] if h and h.strip()})
        cardinals = classify_headsigns(set(heads))
        towards = platform_towards(heads)
        platforms.append(Platform(
            stop_id=raw["stop_id"],
            stop_code=raw.get("stop_code") or "",
            stop_name=gtfs_name,
            headsigns=heads,
            cardinals=cardinals,
            citybound=is_citybound(gtfs_name, cardinals),
            towards=towards,
            arrival_only=is_terminus_arrival(gtfs_name, heads),
        ))
    return Station(
        name=gtfs_name,
        spoken=spoken_name(gtfs_name),
        city_centre=is_city_centre(gtfs_name),
        platforms=platforms,
    )


def catalog_from_dicts(rows: list[dict]) -> list[Station]:
    return [Station.from_dict(r) for r in rows]


def alias_index(stations: list[Station]) -> dict[str, str]:
    """normalized phrase -> GTFS stop_name."""
    idx: dict[str, str] = {}
    for st in stations:
        idx.setdefault(normalize_name(st.name), st.name)
        idx.setdefault(normalize_name(st.spoken), st.name)
    for spoken, gtfs in SPOKEN_TO_GTFS.items():
        idx[normalize_name(spoken)] = gtfs
    for k, v in EXTRA_ALIASES.items():
        idx[normalize_name(k)] = v
    return idx


def find_station(stations: list[Station], spoken: str | None) -> Station | None:
    if not spoken:
        return None
    key = normalize_name(spoken)
    if not key:
        return None
    gtfs = alias_index(stations).get(key)
    if not gtfs:
        return None
    for st in stations:
        if st.name == gtfs:
            return st
    return None


def parse_direction(text: str | None) -> str | None:
    if not text:
        return None
    raw = text.strip()
    if not raw or raw == "?":
        return None
    key = normalize_name(_TOWARDS_PREFIX.sub("", raw))
    if not key:
        return None
    if key in CARDINALS:
        return CARDINALS[key]
    if key in {normalize_name(p) for p in CITY_PHRASES} or key in CITY_PHRASES:
        return "city"
    return key


def _headsign_key(name: str) -> str:
    return normalize_name(name)


def match_platforms(station: Station, direction: str | None) -> list[Platform]:
    usable = station.usable_platforms()
    if not direction:
        return usable
    if direction in ("northbound", "southbound", "eastbound", "westbound"):
        return [p for p in usable if direction in p.cardinals]
    if direction == "city":
        if station.city_centre:
            return []
        return [p for p in usable if p.citybound]
    return [p for p in usable if any(_headsign_key(h) == direction for h in p.headsigns)
            or any(_headsign_key(h) == direction for h in p.towards)]


def options_speech(station: Station) -> str:
    parts = [brief_platform(p.cardinals, p.towards) for p in station.usable_platforms()]
    if not parts:
        return f"Which stop at {station.spoken}?"
    if len(parts) == 1:
        return f"I only have {parts[0]} at {station.spoken}."
    if len(parts) == 2:
        return f"Which direction at {station.spoken}? {parts[0]}, or {parts[1]}?"
    return (f"Which direction at {station.spoken}? "
            + ", ".join(parts[:-1]) + ", or " + parts[-1] + "?")


def bad_direction_speech(station: Station, direction: str) -> str:
    if direction == "city" and station.city_centre:
        return (f"Towards the city is ambiguous at {station.spoken}. "
                + options_speech(station))
    pretty = {
        "northbound": "northbound", "southbound": "southbound",
        "eastbound": "eastbound", "westbound": "westbound",
        "city": "towards the city",
    }.get(direction, f"towards {direction}")
    return f"{station.spoken} doesn't have a {pretty} platform. {options_speech(station)}"


def alexa_station_values(stations: list[Station]) -> list[dict]:
    values = []
    seen: set[str] = set()
    for st in stations:
        name = st.spoken
        if name in seen:
            continue
        seen.add(name)
        synonyms = []
        if st.name != st.spoken:
            synonyms.append(st.name)
        for spoken, gtfs in SPOKEN_TO_GTFS.items():
            if gtfs == st.name and spoken != name:
                synonyms.append(spoken)
        for phrase, gtfs in EXTRA_ALIASES.items():
            if gtfs == st.name:
                synonyms.append(phrase)
        syns: list[str] = []
        for s in synonyms:
            if s and s.casefold() != name.casefold() and s not in syns:
                syns.append(s)
        values.append({"name": {"value": name, "synonyms": syns[:20]}})
    values.sort(key=lambda v: v["name"]["value"])
    return values


def alexa_direction_values() -> list[dict]:
    values = [
        {"name": {"value": "northbound", "synonyms": ["north", "north bound"]}},
        {"name": {"value": "southbound", "synonyms": ["south", "south bound"]}},
        {"name": {"value": "eastbound", "synonyms": ["east", "east bound"]}},
        {"name": {"value": "westbound", "synonyms": ["west", "west bound"]}},
        {"name": {"value": "the city", "synonyms": [
            "city", "city centre", "city center", "into town", "town", "towards the city",
        ]}},
    ]
    for term in ("Broombridge", "Brides Glen", "Tallaght", "Saggart", "Connolly",
                 "The Point", "Parnell", "Sandyford", "Heuston", "Red Cow", "Belgard",
                 "Kingswood"):
        values.append({"name": {"value": term, "synonyms": [f"towards {term}", f"toward {term}"]}})
    return values
