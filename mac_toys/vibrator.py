import asyncio
import time
from asyncio import sleep, run
from threading import Lock, Thread, get_native_id
from random import uniform
from signal import signal, SIGINT
from buttplug import Client, WebsocketConnector, ProtocolSpec, Device, DisconnectedError
from typing import Union, cast, Optional, Callable
from mac_toys.sse_listener import SSEListener, ChatEvent, KillEvent
from mac_toys.tracker import PlayerTracker, UpdateTypes
from mac_toys.helpers import interpolate_value_bounded


class ValueSlider:
    current_value: float = None
    target_value: float = None
    starting_value: float = None
    complete: bool = None
    # Time in ms to fully slide from the starting value to the target
    slide_time: float = None
    # Function to call to apply the interim value to.
    applicator: Callable[[float], None] = None
    _worker_thread: Thread = None
    _cancel_flag: bool = None

    # Make a modification every 20ms
    _application_rate: float = 20.0
    _application_step: float = None

    def __init__(
            self,
            current_value: float,
            target_value: float,
            slide_time: float,
            value_applicator: Callable[[float], None]
    ) -> None:
        self.starting_value = current_value
        self.current_value = self.starting_value
        self.target_value = target_value
        self.slide_time = slide_time
        self.applicator = value_applicator
        self.complete = False
        self.cancel_flag = False
        self._application_step = ((self.target_value - self.starting_value) / self.slide_time) * self._application_rate
        self._worker_thread = Thread(
            target=self.slide,
            name=f"Threaded Value Interpolator {get_native_id()}",
            daemon=True,
        )

    def cancel(self) -> None:
        self._cancel_flag = True
        self._worker_thread.join()

    def join(self) -> None:
        self._worker_thread.join()

    def start(self) -> None:
        self._worker_thread.start()

    def slide(self) -> None:
        while not (self._cancel_flag or self.complete):
            time.sleep(self._application_rate / 1000)
            self.current_value += self._application_step
            self.applicator(self.current_value)

            # Floating point 'close enough' check
            if abs(self.target_value - self.current_value) < 0.0001:
                self.complete = True


class Vibrator:
    client: Client = None
    connector: WebsocketConnector = None
    devices: list[Device] = None

    # Instantaneous vibrations
    current_vibration: float = None
    queue_lock: Lock = None
    # List of vibration orders: [vibrate_intensity, vibrate_time_ms]
    # Needs to be list of lists because need mutable elements
    vibrations: list[list[float]] = None
    # unused
    suspended_vibrations: list[list[float]] = None

    # Ambient background vibration
    last_change_time: float = None
    computed_change_rate: float = None
    computed_ambient_vibration: float = None
    ambient_vibration: float = None
    ambient_vibration_variance: float = None
    ambient_vibration_change_rate: float = None
    ambient_vibration_change_rate_variance: float = None
    # For interpolation stuff
    _initial_intensity: float = None
    _target_intensity: float = None
    _step: float = None
    _interpolation_period: float = None
    _interpolation_in_progress: bool = None

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
        self.ambient_vibration = 0.10
        self.ambient_vibration_variance = 0.05
        self.ambient_vibration_change_rate = 3.0
        self.ambient_vibration_change_rate_variance = 0.5
        self.computed_change_rate = self.ambient_vibration_change_rate
        self.computed_ambient_vibration = self.ambient_vibration
        self.last_change_time = time.time()
        # For interpolation stuff
        self.interpolation_step_period = 10
        self._initial_intensity = 0.0
        self._target_intensity = 0.0
        self._interpolation_period = 0.0
        self._time_remaining = 0.0
        self._step = 0.0
        self._interpolation_in_progress = False

    def _set_target_intensity(self, target_intensity: float) -> None:
        self._target_intensity = target_intensity
        self._initial_intensity = self.ambient_vibration

    def _set_interpolation_period(self, period: float) -> None:
        self._interpolation_period = period
        self._time_remaining = self._interpolation_period
        self._step = (((self._target_intensity - self._initial_intensity) / self._interpolation_period)
                      * self.interpolation_step_period)

    def _interpolation_step(self) -> None:
        """
        Run every 10ms?
        :return: None
        """
        self.current_vibration += self._step
        self._time_remaining -= self.interpolation_step_period

        if abs(self.current_vibration - self._target_intensity) < 1e-6:
            self._interpolation_in_progress = False
            self._step = 0.0
            self._target_intensity = 0.0
            self._interpolation_period = 0.0

    async def _apply_intensity(self) -> None:
        futures = []
        for dev in self.devices:
            for r_act in dev.actuators:
                futures.append(r_act.command(self.current_vibration))

        try:
            async with asyncio.timeout(0.5):
                await asyncio.gather(*futures, return_exceptions=True)
        except DisconnectedError:
            print("Disconnected")
        except TimeoutError:
            print("Timed-out")

    def interpolate_to_intensity(self, target_intensity: float, duration: float) -> None:
        self._set_target_intensity(target_intensity)
        self._set_interpolation_period(duration)
        self._interpolation_in_progress = True

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


def abort(signum, frame):
    print("Received exit signal, ending...")
    _inst = SSEListener(event_endpoint=None)
    if _inst.t_subscriber is not None:
        _inst.shutdown_flag = True
        _inst.t_subscriber.join()
    exit(0)


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
                _vibe.ambient_vibration = max(
                    interpolate_value_bounded(
                        float(_ks), 0.0, 15.0, 0.1, 0.6
                    ),
                    interpolate_value_bounded(
                        float(_ds), 0.0, 5.0, 0.1, 0.6
                    )
                )
                _vibe.ambient_vibration_variance = max(
                    interpolate_value_bounded(
                        float(_ks), 0.0, 15.0, 0.05, 0.33
                    ),
                    interpolate_value_bounded(
                        float(_ds), 0.0, 5.0, 0.05, 0.33
                    )
                )
                _vibe.ambient_vibration_change_rate = min(
                    interpolate_value_bounded(
                        float(_ks), 0.0, 15.0, 6.9, 2.5
                    ),
                    interpolate_value_bounded(
                        float(_ds), 0.0, 5.0, 6.9, 3.1
                    )
                )
                _vibe.ambient_vibration_change_rate_variance = min(
                    interpolate_value_bounded(
                        float(_ks), 0.0, 15.0, 0.5, 0.2
                    ),
                    interpolate_value_bounded(
                        float(_ds), 0.0, 5.0, 0.5, 0.3
                    )
                )
                if len(_updates) > 0:
                    print(f"{_player_tracker.player_name} kill streak: {_ks}, death streak: {_ds}")

                for update in _updates:
                    match update:
                        case UpdateTypes.GOT_KILLED:
                            print("OH NO, YOU DIED -> *VIBRATES IN YOU*")
                            _vibe.add_vibration_order(0.4, 500)
                        case UpdateTypes.KILLED_ENEMY:
                            print("GOOD GIRL/BOY/PUPPY/KITTY -> HAVE A REWARD")
                            _vibe.add_vibration_order(0.5, 666)
                        case UpdateTypes.CRIT_KILLED_ENEMY:
                            print("FAIR AND BALANCED, BITCH! -> *GIBS YOU*")
                            _vibe.add_vibration_order(0.69, 420)
                        case UpdateTypes.GOT_CRIT_KILLED:
                            print("LOL NOOB EZ -> *TOUCHES UR PROSTATE*")
                            _vibe.add_vibration_order(0.77, 360)


def value(new_val: float) -> None:
    print(f"New value: {new_val} at {time.time()}")


if __name__ == "__main__":
    # signal(SIGINT, abort)
    # run(main())
    print(f"Starting slider at {time.time()}")
    _slider = ValueSlider(0.0, 1.0, 1000, value)
    _slider.start()
    print("sleeping...")
    time.sleep(1.5)
    print("attempting to cancel...")
    _slider.cancel()

