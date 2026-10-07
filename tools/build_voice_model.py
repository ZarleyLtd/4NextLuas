"""Build skill-package/interactionModels/custom/en-GB.json from the tram station catalog.

Uses a local GTFS extract if present (.cache/gtfs or .cache/gtfs_luas), otherwise a
fallback list of spoken names so the file can still be regenerated.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common.stations import Station, alexa_direction_values, alexa_station_values, spoken_name

OUT = ROOT / "skill-package" / "interactionModels" / "custom" / "en-GB.json"

FALLBACK_GTFS_NAMES = [
    "Abbey St.", "Balally", "Ballyogan", "Beechwood", "Belgard", "Blackhorse", "Bluebell",
    "Brides Glen", "Broadstone", "Broombridge", "Busáras", "Cabra", "Carrickmines",
    "Central Park", "Charlemont", "Cheeverstown", "Cherrywood", "Citywest", "Connolly",
    "Cookstown", "Cowper", "Dawson", "Dominick", "Drimnagh", "Dundrum", "Fatima",
    "Fettercairn", "Fortunestown", "Four Courts", "George's Dock", "Glencairn",
    "Goldenbridge", "Grangegorman", "Harcourt", "Heuston", "Hospital", "James's",
    "Jervis", "Kilmacud", "Kingswood", "Kylemore", "Laughanstown", "Leopardstown",
    "Marlborough", "Mayor Square", "Milltown", "Museum", "O'Connell - GPO",
    "O'Connell Upr.", "Parnell", "Phibsborough", "Ranelagh", "Red Cow", "Rialto",
    "Saggart", "Sandyford", "Smithfield", "Spencer Dock", "St. Stephen's Green",
    "Stillorgan", "Suir Road", "Tallaght", "The Gallops", "The Point", "Trinity",
    "Westmoreland", "Windy Arbour",
]

NEXT_SAMPLES = [
    "from {station} {direction}",
    "from {station} towards {direction}",
    "from {station} toward {direction}",
    "from {station} to {direction}",
    "{station} towards {direction}",
    "{station} to {direction}",
    "{direction} from {station}",
    "{station} {direction}",
    "{direction}",
    "to get trams from {station} {direction}",
    "to get the next tram from {station} {direction}",
    "trams from {station} {direction}",
    "the next tram from {station} {direction}",
    "when is the next tram from {station} {direction}",
    "what's the next tram from {station} {direction}",
    "next tram from {station} {direction}",
    "from {station} going {direction}",
    "from {station} heading {direction}",
    "{station} going {direction}",
    "{station} heading {direction}",
    "{station} going south",
    "{station} going north",
    "from {station} going south",
    "from {station} going north",
    "from stop {station} {direction}",
    "next tram",
    "next trams",
    "the next tram",
    "for the next tram",
    "for the next trams",
    "when is the next tram",
    "when is my next tram",
    "what's the next tram",
    "what time is the next tram",
    "from my favourite stop",
    "from my stop",
    "for my stop",
    "trams from my favourite stop",
    "the next tram from my favourite stop",
]

QUERY_SAMPLES = [
    "for {query}",
    "from {query}",
    "about {query}",
    "trams from {query}",
    "the next tram from {query}",
    "next tram from {query}",
    "from stop {query}",
    "to get trams from {query}",
]

SET_SAMPLES = [
    "to set my favourite stop to {station}",
    "set my favourite stop to {station}",
    "set my favourite stop to {station} {direction}",
    "set favourite stop {station} {direction}",
    "set my favourite stop",
    "to set my favourite stop",
    "to set my favorite stop",
    "set my favorite stop",
    "change my favourite stop to {station}",
    "to change my favourite stop to {station}",
    "change my favourite stop to {station} {direction}",
    "make {station} my favourite stop",
    "make {station} {direction} my favourite",
    "remember {station}",
    "to remember {station} {direction}",
    "save {station}",
    "to save {station} as my favourite",
    "my stop is {station}",
    "my stop is {station} {direction}",
    "to set my favorite stop to {station}",
    "set my favorite stop to {station}",
    "to set my favourite stop to {station} {direction}",
    "to set my favorite stop to {station} {direction}",
]

SET_QUERY_SAMPLES = [
    "to set my favourite stop to {query}",
    "set my favourite stop to {query}",
    "to set my favorite stop to {query}",
    "set my favorite stop to {query}",
    "remember {query}",
    "to remember {query}",
]

GET_SAMPLES = [
    "for my favourite stop",
    "what is my favourite stop",
    "what's my favourite stop",
    "which stop is my favourite",
    "to remind me of my favourite stop",
    "what stop is saved",
    "for my favorite stop",
    "what is my favorite stop",
]


def load_stations() -> list[Station]:
    for path in (ROOT / ".cache" / "gtfs", ROOT / ".cache" / "gtfs_luas"):
        if (path / "stops.txt").exists() and (path / "stop_times.txt").exists():
            from ingest.gtfs_static import GtfsStatic
            gtfs = GtfsStatic(path)
            rows = gtfs.station_catalog()
            print(f"catalog from {path}: {len(rows)} stations")
            return [Station.from_dict(r) for r in rows]
    print("no GTFS cache; using fallback station names")
    return [Station(name=n, spoken=spoken_name(n), city_centre=False, platforms=[]) for n in FALLBACK_GTFS_NAMES]


def main() -> None:
    stations = load_stations()
    model = {
        "interactionModel": {
            "languageModel": {
                "invocationName": "four next luas",
                "intents": [
                    {
                        "name": "NextTramIntent",
                        "slots": [
                            {"name": "station", "type": "LUAS_STATION"},
                            {"name": "direction", "type": "LUAS_DIRECTION"},
                        ],
                        "samples": NEXT_SAMPLES,
                    },
                    {
                        "name": "NextTramQueryIntent",
                        "slots": [
                            {"name": "query", "type": "AMAZON.SearchQuery"},
                        ],
                        "samples": QUERY_SAMPLES,
                    },
                    {
                        "name": "SetFavouriteStopIntent",
                        "slots": [
                            {"name": "station", "type": "LUAS_STATION"},
                            {"name": "direction", "type": "LUAS_DIRECTION"},
                        ],
                        "samples": SET_SAMPLES,
                    },
                    {
                        "name": "SetFavouriteQueryIntent",
                        "slots": [
                            {"name": "query", "type": "AMAZON.SearchQuery"},
                        ],
                        "samples": SET_QUERY_SAMPLES,
                    },
                    {"name": "GetFavouriteStopIntent", "slots": [], "samples": GET_SAMPLES},
                    {"name": "AMAZON.HelpIntent", "samples": []},
                    {"name": "AMAZON.StopIntent", "samples": []},
                    {"name": "AMAZON.CancelIntent", "samples": []},
                    {"name": "AMAZON.FallbackIntent", "samples": []},
                    {"name": "AMAZON.NavigateHomeIntent", "samples": []},
                ],
                "types": [
                    {"name": "LUAS_STATION", "values": alexa_station_values(stations)},
                    {"name": "LUAS_DIRECTION", "values": alexa_direction_values()},
                ],
            },
            "dialog": {
                "intents": [
                    {
                        "name": "NextTramIntent",
                        "confirmationRequired": False,
                        "prompts": {},
                        "slots": [
                            {
                                "name": "station", "type": "LUAS_STATION",
                                "confirmationRequired": False, "elicitationRequired": False,
                                "prompts": {"elicitation": "Elicit.Slot.station"},
                            },
                            {
                                "name": "direction", "type": "LUAS_DIRECTION",
                                "confirmationRequired": False, "elicitationRequired": False,
                                "prompts": {"elicitation": "Elicit.Slot.direction"},
                            },
                        ],
                    },
                    {
                        "name": "SetFavouriteStopIntent",
                        "confirmationRequired": False,
                        "prompts": {},
                        "slots": [
                            {
                                "name": "station", "type": "LUAS_STATION",
                                "confirmationRequired": False, "elicitationRequired": False,
                                "prompts": {"elicitation": "Elicit.Slot.station"},
                            },
                            {
                                "name": "direction", "type": "LUAS_DIRECTION",
                                "confirmationRequired": False, "elicitationRequired": False,
                                "prompts": {"elicitation": "Elicit.Slot.direction"},
                            },
                        ],
                    },
                ],
                "delegationStrategy": "SKILL_RESPONSE",
            },
            "prompts": [
                {
                    "id": "Elicit.Slot.station",
                    "variations": [
                        {"type": "PlainText", "value": "Which Luas stop?"},
                        {"type": "PlainText", "value": "What's the name of the stop?"},
                    ],
                },
                {
                    "id": "Elicit.Slot.direction",
                    "variations": [
                        {"type": "PlainText", "value": "Which direction?"},
                        {"type": "PlainText", "value": "Northbound, southbound, towards the city, or towards a terminus?"},
                    ],
                },
            ],
        }
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(stations)} stations)")


if __name__ == "__main__":
    main()
