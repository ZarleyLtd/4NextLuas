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


HELP = ("I can tell you the next Luas trams from a stop. Say, from, followed by the stop name, "
        "for example, from Dundrum northbound. You can say northbound, southbound, eastbound, "
        "or westbound, towards the city, or towards a terminus like Broombridge. "
        "To save a stop, say, set my favourite stop to, and the name and direction. "
        "After that, just ask me for the next tram. What would you like?")
NO_FAVOURITE = ("You haven't set a favourite stop yet. Say, set my favourite stop to, followed by "
                "the stop name and direction, for example, Dundrum northbound.")
ASK_STATION = "Which Luas stop?"
ERROR = "Sorry, I had trouble getting the tram times. Please try again in a moment."
NOT_READY = "Sorry, the tram timetable isn't loaded yet. Please try again later."


def user_id(handler_input: HandlerInput) -> str:
    return handler_input.request_envelope.context.system.user.user_id


def slot_value(handler_input: HandlerInput, name: str) -> str | None:
    intent = getattr(handler_input.request_envelope.request, "intent", None)
    slots = getattr(intent, "slots", None) or {}
    slot = slots.get(name)
    value = getattr(slot, "value", None) if slot else None
    return value.strip() if value and value != "?" else None


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


def handle_resolve(handler_input: HandlerInput, station: str | None, direction: str | None,
                   no_station_prompt: str) -> Response:
    svc = service()
    result = svc.resolve(station, direction)
    if result.status == "ok" and result.ref:
        return respond_with_trams(handler_input, result.ref)
    if result.status == "need_station":
        return elicit(handler_input, no_station_prompt, "station")
    if result.status in ("need_direction", "bad_direction") and result.elicit:
        return elicit(handler_input, result.prompt, result.elicit)
    return handler_input.response_builder.speak(result.prompt).set_should_end_session(True).response


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        fav = service().get_favourite(user_id(handler_input))
        if fav:
            return respond_with_trams(handler_input, fav)
        speech = ("Welcome to four next luas. Ask me for trams from a stop, for example, "
                  "from Dundrum northbound. Or say, set my favourite stop to, and the stop name.")
        return handler_input.response_builder.speak(speech).ask(ASK_STATION).response


class NextTramIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("NextTramIntent")(handler_input)

    def handle(self, handler_input):
        station = slot_value(handler_input, "station")
        direction = slot_value(handler_input, "direction")
        if not station:
            fav = service().get_favourite(user_id(handler_input))
            if fav:
                return respond_with_trams(handler_input, fav)
            return elicit(handler_input, NO_FAVOURITE + " Or tell me a stop name now. " + ASK_STATION, "station")
        return handle_resolve(handler_input, station, direction, ASK_STATION)


class SetFavouriteStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("SetFavouriteStopIntent")(handler_input)

    def handle(self, handler_input):
        station = slot_value(handler_input, "station")
        direction = slot_value(handler_input, "direction")
        if not station:
            return elicit(handler_input, "Which stop should I save as your favourite?", "station")
        svc = service()
        result = svc.resolve(station, direction)
        if result.status == "ok" and result.ref:
            svc.set_favourite(user_id(handler_input), result.ref)
            speech = (f"Done. Your favourite stop is now {result.ref.spoken_name}. "
                      "From now on, just ask me for the next tram.")
            return (handler_input.response_builder.speak(speech)
                    .set_card(SimpleCard("Favourite stop saved", result.ref.spoken_name))
                    .set_should_end_session(True).response)
        if result.status in ("need_direction", "bad_direction") and result.elicit:
            return elicit(handler_input, result.prompt, result.elicit)
        return handler_input.response_builder.speak(result.prompt).set_should_end_session(True).response


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
for h in (LaunchRequestHandler(), NextTramIntentHandler(), SetFavouriteStopIntentHandler(),
          GetFavouriteStopIntentHandler(), HelpIntentHandler(), CancelOrStopIntentHandler(),
          FallbackIntentHandler(), SessionEndedRequestHandler()):
    sb.add_request_handler(h)
sb.add_exception_handler(CatchAllExceptionHandler())

_sdk_handler = sb.lambda_handler()


def handler(event, context):
    verify_skill_id(event)
    return _sdk_handler(event, context)
