from __future__ import annotations

from json import loads
from dataclasses import dataclass
from threading import Thread, Lock
from queue import Queue
from requests import RequestException, ConnectionError
from urllib3.exceptions import ReadTimeoutError
from requests_sse import EventSource, InvalidStatusCodeError, InvalidContentTypeError, MessageEvent


class Singleton(type):
    _instances = {}
    _lock = Lock()

    def __call__(cls, *args, **kwargs):
        with cls._lock:
            if cls not in cls._instances:
                cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


@dataclass
class KillEvent:
    killer: tuple[str, str] = None
    victim: tuple[str, str] = None
    weapon: str = None
    crit: bool = None

    @classmethod
    def from_sse(cls, sse_json: dict) -> KillEvent:
        _event: dict = sse_json['event']
        _killer = (_event.get('killer_name'), _event.get('killer_steamid'))
        _victim = (_event.get('victim_name'), _event.get('victim_steamid'))
        _weapon = _event.get('weapon')
        _crit = _event.get('crit')
        return cls(_killer, _victim, _weapon, _crit)


@dataclass
class ChatEvent:
    author: tuple[str, str] = None
    message: str = None

    @classmethod
    def from_sse(cls, sse_json: dict) -> ChatEvent:
        _event: dict = sse_json['event']
        _author = (_event.get('player_name'), _event.get('steamid'))
        _message = _event.get('message')
        return cls(_author, _message)


def process_event(sse_event_message: MessageEvent) -> ChatEvent | KillEvent | None:
    sse_event = loads(sse_event_message.data)
    match sse_event['type']:
        case 'ChatMessage':
            return ChatEvent.from_sse(sse_event)
        case 'PlayerKill':
            return KillEvent.from_sse(sse_event)
        case _:
            return None


class SSEListener(metaclass=Singleton):
    event_endpoint: str = None
    q_subscriber: Queue = None
    t_subscriber: Thread = None

    shutdown_flag: bool = False

    @classmethod
    def with_mac(
            cls,
            mac_api_proto: str = "http",
            mac_api_base_url: str = "127.0.0.1",
            mac_api_port: int = 3621,
            mac_api_endpoint: str = "/mac/game/events/v1"
    ) -> SSEListener:
        return cls(f"{mac_api_proto}://{mac_api_base_url}:{mac_api_port}{mac_api_endpoint}")

    def __init__(self, event_endpoint: str | None) -> None:
        if self.event_endpoint is None:
            self.event_endpoint = event_endpoint
        if self.q_subscriber is None:
            self.q_subscriber = Queue()

        if self.t_subscriber is None:
            _thread = Thread(
                target=self.mac_subscribe,
                name="mac-sse-listener-thread",
                daemon=True
            )

            self.t_subscriber = _thread
            self.t_subscriber.start()

    def mac_subscribe(self):
        # TODO: implement onError
        print(f"Starting MAC SSE Subscriber, -> {self.event_endpoint}")
        with EventSource(self.event_endpoint) as event_source:
            try:
                for event in event_source:
                    # print("++ New event")
                    _event = process_event(event)
                    self.q_subscriber.put(_event)

                    if self.shutdown_flag:
                        raise GeneratorExit
            except (InvalidStatusCodeError, InvalidContentTypeError):
                # Ignore these errors for now
                print("Invalid status code or content type, ignoring message.")
            except RequestException:
                # Ignore this one too, but im inclined to always ignore it, unlike the above
                print("Some sort of request exception!")

        print("Exiting MAC SSE subscriber")
