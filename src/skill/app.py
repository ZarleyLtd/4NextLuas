"""Alexa skill Lambda handler for 4NextLuas (invocation name: "four next luas")."""
from __future__ import annotations

import logging

from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import is_intent_name, is_request_type
from ask_sdk_model import Response
from ask_sdk_model.dialog import ElicitSlotDirective
from ask_sdk_model.ui import SimpleCard

from src.common import config
from src.common.rt_cache import RealtimeCache
from src.common.store import Store
from src.common.stations import split_station_and_direction
from src.skill.service import LuasService, StopRef, TimetableNotLoaded

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)

_service: LuasService | None = None


def service() -> LuasService:
    global _service
    if _service is None:
        store = Store(config.TABLE_NAME, config.REGION)
        _service = LuasService(store, RealtimeCache(store, config.nta_api_key()))
    return _service


HELP = ("I can tell you the next Luas trams from a stop. Say, for example, Dundrum southbound. "
        "You can say southbound or going south, northbound or going north, "
        "eastbound, westbound, towards the city, or towards a terminus like Broombridge. "
        "To save a stop, say, set my favourite stop to, and the name and direction. "
        "After that, just ask me for the next tram. What would you like?")
NO_FAVOURITE = ("You haven't set a favourite stop yet. Say, set my favourite stop to, followed by "
                "the stop name and direction, for example, Dundrum northbound.")
MISS_STATION = ("I didn't catch which stop. Say the stop name and direction, for example, Dundrum southbound.")
ASK_STATION = "Which Luas stop?"
PENDING_SET_FAV = "set_favourite"
ASK_FAVOURITE_STOP = "Say the stop name and direction, for example Broadstone southbound."
ERROR = "Sorry, I had trouble getting the tram times. Please try again in a moment."
NOT_READY = "Sorry, the tram timetable isn't loaded yet. Please try again later."


def user_id(handler_input: HandlerInput) -> str:
    return handler_input.request_envelope.context.system.user.user_id


def slot_value(handler_input: HandlerInput, name: str) -> str | None:
    """Spoken slot text, including slotValue payloads Alexa sometimes sends instead of value."""
    intent = getattr(handler_input.request_envelope.request, "intent", None)
    slots = getattr(intent, "slots", None) or {}
    slot = slots.get(name)
    if not slot:
        return None
    candidates: list[str] = []

    def _add(raw: str | None) -> None:
        if raw and raw != "?":
            text = str(raw).strip()
            if text:
                candidates.append(text)

    _add(getattr(slot, "value", None))
    sv = getattr(slot, "slot_value", None)
    _add(getattr(sv, "value", None) if sv is not None else None)
    for item in getattr(sv, "values", None) or []:
        _add(getattr(item, "value", None))
        inner = getattr(item, "value", None)
        _add(getattr(inner, "value", None) if inner is not None and not isinstance(inner, str) else None)

    resolved = None
    sources = [getattr(slot, "resolutions", None)]
    if sv is not None:
        sources.append(getattr(sv, "resolutions", None))
    for resolutions in sources:
        authorities = getattr(resolutions, "resolutions_per_authority", None) if resolutions else None
        for auth in authorities or []:
            status = getattr(getattr(auth, "status", None), "code", None)
            values = getattr(auth, "values", None) or []
            if str(status).endswith("ER_SUCCESS_MATCH") and values:
                name_obj = getattr(values[0], "value", None)
                resolved = getattr(name_obj, "name", None) or getattr(name_obj, "id", None)
                if resolved:
                    _add(str(resolved).strip())
                break
    if not candidates:
        return None
    # Prefer the longest string so "Dundrum southbound" is kept over resolved "Dundrum".
    return max(candidates, key=len)


def respond_with_trams(handler_input: HandlerInput, ref: StopRef) -> Response:
    result = service().next_trams(ref)
    return (handler_input.response_builder
            .speak(result.speech)
            .set_card(SimpleCard(result.card_title, result.card_text))
            .set_should_end_session(True)
            .response)


def elicit(handler_input: HandlerInput, prompt: str, slot_name: str) -> Response:
    ask = ASK_STATION if slot_name == "station" else "Which direction?"
    return (handler_input.response_builder
            .speak(prompt).ask(ask)
            .add_directive(ElicitSlotDirective(slot_to_elicit=slot_name))
            .response)


def session_attrs(handler_input: HandlerInput) -> dict:
    return handler_input.attributes_manager.session_attributes


def ask_for_favourite_stop(handler_input: HandlerInput, prompt: str) -> Response:
    """Keep the session open without ElicitSlot so 'Broadstone southbound' is a full intent."""
    session_attrs(handler_input)["pending_action"] = PENDING_SET_FAV
    return (handler_input.response_builder
            .speak(prompt).ask(ASK_FAVOURITE_STOP)
            .response)


def save_favourite(handler_input: HandlerInput, station: str | None, direction: str | None) -> Response:
    log.info("SetFavourite station=%r direction=%r pending=%r",
             station, direction, session_attrs(handler_input).get("pending_action"))
    if not station:
        return ask_for_favourite_stop(handler_input, "Which stop should I save as your favourite?")
    svc = service()
    result = svc.resolve(station, direction)
    if result.status == "ok" and result.ref:
        svc.set_favourite(user_id(handler_input), result.ref)
        session_attrs(handler_input).pop("pending_action", None)
        session_attrs(handler_input).pop("pending_station", None)
        speech = (f"Done. Your favourite stop is now {result.ref.spoken_name}. "
                  "From now on, just ask me for the next tram.")
        return (handler_input.response_builder.speak(speech)
                .set_card(SimpleCard("Favourite stop saved", result.ref.spoken_name))
                .set_should_end_session(True).response)
    if result.status in ("need_direction", "bad_direction") and result.elicit:
        peeled, _ = split_station_and_direction(station, direction)
        if peeled:
            session_attrs(handler_input)["pending_station"] = peeled
        session_attrs(handler_input)["pending_action"] = PENDING_SET_FAV
        return elicit(handler_input, result.prompt, result.elicit)
    session_attrs(handler_input).pop("pending_action", None)
    return handler_input.response_builder.speak(result.prompt).set_should_end_session(True).response


def handle_resolve(handler_input: HandlerInput, station: str | None, direction: str | None,
                   no_station_prompt: str, elicit_slots: bool = True) -> Response:
    svc = service()
    result = svc.resolve(station, direction)
    if result.status == "ok" and result.ref:
        session_attrs(handler_input).pop("pending_station", None)
        return respond_with_trams(handler_input, result.ref)
    if result.status == "need_station":
        if elicit_slots:
            return elicit(handler_input, no_station_prompt, "station")
        return handler_input.response_builder.speak(no_station_prompt).ask(ASK_STATION).response
    if result.status in ("need_direction", "bad_direction") and result.elicit:
        peeled, _ = split_station_and_direction(station, direction)
        if peeled:
            session_attrs(handler_input)["pending_station"] = peeled
        if elicit_slots:
            return elicit(handler_input, result.prompt, result.elicit)
        return handler_input.response_builder.speak(result.prompt).ask("Which direction?").response
    return handler_input.response_builder.speak(result.prompt).set_should_end_session(True).response


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        fav = service().get_favourite(user_id(handler_input))
        if fav:
            return respond_with_trams(handler_input, fav)
        speech = ("Welcome to four next luas. Ask me for trams from a stop, for example, "
                  "Dundrum southbound. Or say, set my favourite stop to, and the stop name.")
        return handler_input.response_builder.speak(speech).ask(ASK_STATION).response


class NextTramIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("NextTramIntent")(handler_input)

    def handle(self, handler_input):
        station = slot_value(handler_input, "station") or session_attrs(handler_input).get("pending_station")
        direction = slot_value(handler_input, "direction")
        intent = getattr(handler_input.request_envelope.request, "intent", None)
        raw = {}
        for key, slot in (getattr(intent, "slots", None) or {}).items():
            raw[key] = slot.to_dict() if hasattr(slot, "to_dict") else str(slot)
        log.info("NextTramIntent station=%r direction=%r raw=%s", station, direction, raw)
        if session_attrs(handler_input).get("pending_action") == PENDING_SET_FAV:
            return save_favourite(handler_input, station, direction)
        if not station:
            fav = service().get_favourite(user_id(handler_input))
            if fav:
                return respond_with_trams(handler_input, fav)
            return elicit(handler_input, MISS_STATION, "station")
        return handle_resolve(handler_input, station, direction, ASK_STATION)


class NextTramQueryIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("NextTramQueryIntent")(handler_input)

    def handle(self, handler_input):
        query = slot_value(handler_input, "query")
        log.info("NextTramQueryIntent query=%r", query)
        if session_attrs(handler_input).get("pending_action") == PENDING_SET_FAV:
            return save_favourite(handler_input, query, None)
        if not query:
            fav = service().get_favourite(user_id(handler_input))
            if fav:
                return respond_with_trams(handler_input, fav)
            return handler_input.response_builder.speak(MISS_STATION).ask(ASK_STATION).response
        return handle_resolve(handler_input, query, None, MISS_STATION, elicit_slots=False)


class SetFavouriteStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("SetFavouriteStopIntent")(handler_input)

    def handle(self, handler_input):
        station = slot_value(handler_input, "station") or session_attrs(handler_input).get("pending_station")
        direction = slot_value(handler_input, "direction")
        return save_favourite(handler_input, station, direction)


class SetFavouriteQueryIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("SetFavouriteQueryIntent")(handler_input)

    def handle(self, handler_input):
        query = slot_value(handler_input, "query")
        log.info("SetFavouriteQueryIntent query=%r", query)
        return save_favourite(handler_input, query, None)


class GetFavouriteStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("GetFavouriteStopIntent")(handler_input)

    def handle(self, handler_input):
        fav = service().get_favourite(user_id(handler_input))
        speech = f"Your favourite stop is {fav.spoken_name}." if fav else NO_FAVOURITE
        return handler_input.response_builder.speak(speech).set_should_end_session(True).response


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.speak(HELP).ask(ASK_STATION).response


class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.CancelIntent")(handler_input) or is_intent_name("AMAZON.StopIntent")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.speak("Goodbye.").set_should_end_session(True).response


class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        if session_attrs(handler_input).get("pending_action") == PENDING_SET_FAV:
            return ask_for_favourite_stop(
                handler_input, "Sorry, I didn't catch that. " + ASK_FAVOURITE_STOP)
        speech = "Sorry, I didn't catch that. " + HELP
        return handler_input.response_builder.speak(speech).ask(ASK_STATION).response


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        if isinstance(exception, TimetableNotLoaded):
            log.error("timetable not loaded: %s", exception)
            speech = NOT_READY
        else:
            log.exception("unhandled error")
            speech = ERROR
        return handler_input.response_builder.speak(speech).set_should_end_session(True).response


class SkillIdVerificationError(Exception):
    pass


def _application_id(event: dict) -> str | None:
    system = ((event.get("context") or {}).get("System") or {})
    app = system.get("application") or ((event.get("session") or {}).get("application") or {})
    return app.get("applicationId")


def verify_skill_id(event: dict) -> None:
    """ask-sdk only supports a single skill ID; we allow several (e.g. dev + live copies)."""
    if not config.SKILL_IDS:
        return
    app_id = _application_id(event)
    if app_id not in config.SKILL_IDS:
        log.error("skill ID verification failed for %r", app_id)
        raise SkillIdVerificationError(f"unexpected skill ID {app_id!r}")


sb = SkillBuilder()
for h in (LaunchRequestHandler(), NextTramIntentHandler(), NextTramQueryIntentHandler(),
          SetFavouriteStopIntentHandler(), SetFavouriteQueryIntentHandler(),
          GetFavouriteStopIntentHandler(), HelpIntentHandler(),
          CancelOrStopIntentHandler(), FallbackIntentHandler(), SessionEndedRequestHandler()):
    sb.add_request_handler(h)
sb.add_exception_handler(CatchAllExceptionHandler())

_sdk_handler = sb.lambda_handler()


def handler(event, context):
    verify_skill_id(event)
    return _sdk_handler(event, context)
