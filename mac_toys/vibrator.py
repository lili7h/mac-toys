import asyncio
import time
from asyncio import sleep, run
from threading import Lock
from random import uniform
from buttplug import Client, WebsocketConnector, ProtocolSpec, Device, DisconnectedError
from typing import Union, cast, Optional
from mac_toys.sse_listener import SSEListener, ChatEvent, KillEvent
from mac_toys.tracker import PlayerTracker, UpdateTypes


class Vibrator:
    client: Client = None
    connector: WebsocketConnector = None
    devices: list[Device] = None

    ## Instantaneous vibrations
    current_vibration: float = None
    queue_lock: Lock = None
    # List of vibration orders: [vibrate_intensity, vibrate_time_ms]
    # Needs to be list of lists because need mutable elements
    vibrations: list[list[float]] = None
    # unused
    suspended_vibrations: list[list[float]] = None

    ## Ambient background vibration
    last_change_time: float = None
    computed_change_rate: float = None
    computed_ambient_vibration: float = None
    ambient_vibration: float = None
    ambient_vibration_variance: float = None
    ambient_vibration_change_rate: float = None
    ambient_vibration_change_rate_variance: float = None

    async def connect_and_scan(self) -> None:
        assert self.connector is not None

        # Finally, we connect.
        # If this succeeds, we'll be connected. If not, we'll probably have some
        # sort of exception thrown of type ButtplugError.
        try:
            await self.client.connect(self.connector)
        except Exception as e:
            print(f"Could not connect to server, exiting: {e}")
            return

        if len(self.client.devices) == 0:
            print(f"Scanning for devices now, see you in 10s!")
            await self.client.start_scanning()
            await sleep(10)
            await self.client.stop_scanning()
            print(f"Done.")
        else:
            print(f"Found devices connected, assuming no scan needed.")

        if len(self.client.devices) > 0:
            print(f"Found {len(self.client.devices)} devices!")
        else:
            print(f"Found no devices :(")

    def __init__(self, ws_host: str = "127.0.0.1", port: int = 12345):
        self.client = Client("MAC Toys Client", ProtocolSpec.v3)
        self.connector = WebsocketConnector(f"ws://{ws_host}:{port}")
        self.queue_lock = Lock()
        self.vibrations = []
        self.current_vibration = 0.0
        self.ambient_vibration = 0.20
        self.ambient_vibration_variance = 0.2
        self.ambient_vibration_change_rate = 2.0
        self.ambient_vibration_change_rate_variance = 0.5
        self.computed_change_rate = self.ambient_vibration_change_rate
        self.computed_ambient_vibration = self.ambient_vibration
        self.last_change_time = time.time()

    def set_device(self):
        self.devices = list(self.client.devices.values())

    async def issue_command(self, intensity: float):
        """
        Sets all actuators in all devices to the given intensity

        :param intensity: float between 0 and 1 inclusive defining intensity of vibration
        :return: None
        """
        assert 0 <= intensity <= 1
        if intensity != self.current_vibration:
            print(f"(setting intensity to {intensity})")

        self.current_vibration = intensity
        _total_vibration = min(self.current_vibration + self.computed_ambient_vibration, 0.99)
        futures = []
        for dev in self.devices:
            for r_act in dev.actuators:
                futures.append(r_act.command(_total_vibration))

        try:
            async with asyncio.timeout(0.5):
                await asyncio.gather(*futures, return_exceptions=True)
        except DisconnectedError:
            print("Disconnected")
        except TimeoutError:
            print("Timed-out")

    def add_vibration_order(self, intensity: float, vibrate_ms: float) -> None:
        with self.queue_lock:
            self.vibrations.append([intensity, vibrate_ms])

    async def process_queues(self, time_passed: float) -> float:
        if not self.client.connected:
            print("Showing not connected, re-running connection!")
            await self.client.connect(self.connector)
            self.add_vibration_order(0.33, 150)

        if len(self.vibrations) == 0:
            return 0.0

        with self.queue_lock:
            _to_drop = []
            for inten_time_pair in self.vibrations:
                inten_time_pair[1] -= time_passed
                if inten_time_pair[1] < 0:
                    _to_drop.append(inten_time_pair)

            for elem in _to_drop:
                self.vibrations.remove(elem)

            if len(self.vibrations) > 0:
                _greatest_intensity = max([x[0] for x in self.vibrations])
            else:
                _greatest_intensity = 0.0
        return _greatest_intensity

    async def settle_ambience(self) -> None:
        _now = time.time()
        if _now - self.last_change_time > self.computed_change_rate:
            _new_change_rate = uniform(
                max(0.33,
                    self.ambient_vibration_change_rate - self.ambient_vibration_change_rate_variance
                    ),
                self.ambient_vibration_change_rate + self.ambient_vibration_change_rate_variance
            )
            _new_ambient_intensity = uniform(
                max(0.0,
                    self.ambient_vibration - self.ambient_vibration_variance,
                    ),
                min(0.99,
                    self.ambient_vibration + self.ambient_vibration_variance
                    )
            )
            self.last_change_time = _now
            self.computed_change_rate = _new_change_rate
            self.computed_ambient_vibration = _new_ambient_intensity
            print(f"New ambient vibration of {_new_ambient_intensity:.2} baseline.")
            await self.issue_command(self.current_vibration)

    async def queue_manage(self, last_time) -> float:
        _now = time.time() * 1000
        _time_elapsed = _now - last_time

        _new_intensity = await self.process_queues(_time_elapsed)
        await self.issue_command(_new_intensity)
        return _now


async def main():
    _vibe = Vibrator(ws_host="localhost")
    await _vibe.connect_and_scan()
    _vibe.set_device()

    # TODO: make this parameterized / pulled from MAC
    _player_tracker = PlayerTracker("Lilith", "76561198071482715")
    _sse_listener = SSEListener.with_mac()

    _last_time = time.time() * 1000
    _time_elapsed: float = 0.0

    while True:
        _last_time = await _vibe.queue_manage(_last_time)
        await _vibe.settle_ambience()
        if not _sse_listener.q_subscriber.empty():
            event = cast(Union[KillEvent | ChatEvent], _sse_listener.q_subscriber.get())
            _ks: Optional[int] = None
            _ds: Optional[int] = None
            _updates: list[UpdateTypes]
            if isinstance(event, ChatEvent):
                # print(f"Chat: {event}")
                _updates = _player_tracker.handle_chat_message(event)
                if len(_updates) > 0:
                    print(f"Notable Chat Event: {event}")
                for update in _updates:
                    match update:
                        case UpdateTypes.CHAT_YOU_SAID_UWU:
                            print("YOU SAID UWU/OWO -> GET VIBED")
                            _vibe.add_vibration_order(0.5, 300)
                        case UpdateTypes.CHAT_FUCK_YOU:
                            print("SOMEONES ANGRY -> MMM BZZZZZZ")
                            _vibe.add_vibration_order(0.35, 200)

            elif isinstance(event, KillEvent):
                # print(f"Kill: {event}")
                _ks, _ds, _updates = _player_tracker.add_kill_event(event)
                if len(_updates) > 0:
                    print(f"Notable Kill Event: {event}")
                for update in _updates:
                    match update:
                        case UpdateTypes.GOT_KILLED:
                            print("OH NO, YOU DIED -> *VIBRATES IN YOU*")
                            _vibe.add_vibration_order(0.5, 500)
                        case UpdateTypes.KILLED_ENEMY:
                            print("GOOD GIRL/BOY/PUPPY/KITTY -> HAVE A REWARD")
                            _vibe.add_vibration_order(0.66, 666)


if __name__ == "__main__":
    run(main())
