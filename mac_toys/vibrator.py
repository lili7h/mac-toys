from __future__ import annotations

__version__ = "0.1.0a"

import asyncio
import queue
import time
from rich import print as rprint
from asyncio import sleep, run, get_running_loop, new_event_loop, set_event_loop
from threading import Lock, Thread, get_native_id
from queue import Queue
from random import uniform
from signal import signal, SIGINT
from buttplug import Client, WebsocketConnector, ProtocolSpec, Device, DisconnectedError
from typing import Union, cast, Optional, Callable, Coroutine, Any
from mac_toys.sse_listener import SSEListener, ChatEvent, KillEvent, Singleton
from mac_toys.tracker import PlayerTracker, UpdateTypes
from mac_toys.helpers import interpolate_value_bounded
from mac_toys.thread_manager import ThreadedActor, Agent


class ValueSlider:
    _current_value: float = None
    target_value: float = None
    starting_value: float = None
    _time_remaining: float = None
    complete: bool = None
    # Time in ms to fully slide from the starting value to the target
    slide_time: float = None
    # Function to call to apply the interim value to.
    applicator: Callable[[float], None] = None
    _worker_thread: Thread = None
    _cancel_flag: bool = None
    _running: bool = None

    # Make a modification every 50ms
    _application_rate: float = 5.0
    _application_step: float = None

    # Tracking value lock to avoid race conditions (not overally necessary since other threads will be RO)
    _write_lock: Lock = None

    def __init__(
            self,
            current_value: float,
            target_value: float,
            slide_time: float,
            value_applicator: Callable[[float], None]
    ) -> None:
        self.starting_value = current_value
        self._current_value = self.starting_value
        self.slide_time = slide_time
        self._time_remaining = self.slide_time
        self.target_value = target_value
        self.applicator = value_applicator
        self.complete = False
        self.cancel_flag = False
        self._running = False
        self._application_step = ((self.target_value - self.starting_value) / self.slide_time) * self._application_rate
        self._write_lock = Lock()

        self._worker_thread = Thread(
            target=self.slide,
            name=f"Threaded Value Interpolator {get_native_id()}",
            daemon=True,
        )

    def __str__(self) -> str:
        return (f"ValueSlider({self.starting_value:.2}->{self.target_value:.2}@{self.slide_time})"
                f"::{self._current_value:.2}@{self._time_remaining:.2}")

    def cancel(self) -> None:
        self._cancel_flag = True
        if self._worker_thread.ident:
            self._worker_thread.join()
        self._running = False

    @property
    def has_started(self) -> bool:
        return self._running

    def join(self) -> None:
        self._worker_thread.join()

    def start(self) -> None:
        self._worker_thread.start()
        self._running = True

    def matches_direction(self, other_slide: ValueSlider) -> bool:
        return self.slide_direction == other_slide.slide_direction

    def has_greater_magnitude_than(self, other_slide: ValueSlider) -> bool:
        if self.matches_direction(other_slide):
            if other_slide.slide_direction == -1:
                return self.target_value < other_slide.target_value
            elif other_slide.slide_direction == 1:
                return self.target_value > other_slide.target_value
            # 0 direction slides are kinda undefined behaviour
            else:
                return self.target_value >= other_slide.target_value
        else:
            raise ValueError("The directions between this and the other slide don't match.")

    @property
    def slide_direction(self) -> int:
        """
        Get the direction of the slide instruction, i.e. a positive slide or a negative slide

        A positive slide is when the final value is _greater_ than the starting value.

        :return: -1, 0, or 1
        """
        if self.target_value == self.starting_value:
            return 0
        elif self.target_value > self.starting_value:
            return 1
        else:
            return -1

    def get_time_remaining(self) -> float:
        """
        Get the time remaining in ms until the slide is complete .
        :return: 0 if complete, positive number if in progress or not started.
        """
        if self.complete:
            return 0
        else:
            with self._write_lock:
                return self._time_remaining

    def get_current_value(self) -> float:
        with self._write_lock:
            return self._current_value

    def slide(self) -> None:
        if self.target_value == self._current_value:
            self.complete = True
            self._running = False

        while not (self._cancel_flag or self.complete):
            time.sleep(self._application_rate / 1000)
            with self._write_lock:
                self._current_value += self._application_step
                self._time_remaining -= self._application_rate
            self.applicator(self._current_value)

            # Floating point 'close enough' check
            if abs(self.target_value - self._current_value) < 0.0001:
                self.complete = True
                self._running = False


class IntensityController:
    ambient_intensity_slider: ValueSlider = None
    _ambient_intensity: float = None
    instant_intensity_slider: ValueSlider = None
    _instant_intensity: float = None
    _combined_intensity: float = None
    _applicator_func: Callable[[float], None] = None
    _applicator_thread: Thread = None
    # how often the applicator function is called in ms (i.e. value 66.66 implies once every ~66.66ms)
    _applicator_regularity: float = None
    _running: bool = True

    def __init__(
            self,
            applicator_function: Callable[[float], None],
            frequency: float = 5
    ) -> None:
        self._ambient_intensity = 0.0
        self._instant_intensity = 0.0
        self._applicator_regularity = (1000.0 / frequency)
        self._running = False
        self._applicator_thread = Thread(
            target=self.threaded_apply,
            name="Intensity Controller Applicator Thread",
            daemon=True
        )
        self._applicator_func = applicator_function

    def start(self) -> None:
        self._running = True
        self._applicator_thread.start()

    def stop(self) -> None:
        self._running = False
        self._applicator_thread.join()

    @property
    def combined_intensity(self) -> float:
        self.set_combined_intensity()
        return self._combined_intensity

    def set_combined_intensity(self) -> None:
        self._combined_intensity = min(1.0, max(0.0, self._ambient_intensity + self._instant_intensity))

    def set_ambient_intensity_slider(self, slider: ValueSlider, *, inherit_starting: bool = True) -> None:
        if self.ambient_intensity_slider is not None:
            if self.ambient_intensity_slider.complete:
                self.ambient_intensity_slider.join()
            else:
                self.ambient_intensity_slider.cancel()

        if inherit_starting:
            slider.starting_value = self._ambient_intensity
        self.ambient_intensity_slider = slider
        self.ambient_intensity_slider.start()

    def set_instant_intensity_slider(
            self,
            slider: ValueSlider, *,
            inherit_starting: bool = True,
            inherit_ending: bool = False
    ) -> None:
        _ending = 0.0
        if self.instant_intensity_slider is not None:
            if inherit_ending:
                _ending = self.instant_intensity_slider.target_value
            if self.instant_intensity_slider.complete:
                self.instant_intensity_slider.join()
            else:
                self.instant_intensity_slider.cancel()

        if inherit_starting:
            slider.starting_value = self._instant_intensity
        if inherit_ending:
            slider.target_value = _ending
        self.instant_intensity_slider = slider
        self.instant_intensity_slider.start()

    def set_ambient_intensity(self, value: float) -> None:
        self._ambient_intensity = value

    def set_instant_intensity(self, value: float) -> None:
        self._instant_intensity = value

    def get_ambient_intensity(self) -> float:
        return self._ambient_intensity

    def get_instant_intensity(self) -> float:
        return self._instant_intensity

    def threaded_apply(self) -> None:
        _made_new: bool = False
        try:
            loop = get_running_loop()
        except RuntimeError:
            _made_new = True
            loop = new_event_loop()
            set_event_loop(loop)

        while self._running:
            loop.run_until_complete(self.apply())
            time.sleep(self._applicator_regularity / 1000)
        if _made_new:
            loop.close()

        if self.ambient_intensity_slider is not None:
            self.ambient_intensity_slider.cancel()
        if self.instant_intensity_slider is not None:
            self.instant_intensity_slider.cancel()

    async def apply(self) -> None:
        self._applicator_func(self.combined_intensity)

    def is_running(self) -> bool:
        return self._running


class AmbienceController(ThreadedActor):
    # Ambient background vibration
    last_change_time: float = None
    computed_change_rate: float = None
    computed_ambient_vibration: float = None
    ambient_vibration: float = None
    ambient_vibration_variance: float = None
    ambient_vibration_change_rate: float = None
    ambient_vibration_change_rate_variance: float = None
    # application
    intensity_controller: IntensityController = None
    # control
    _stop_flag: bool = None
    _running: bool = None
    # update lock
    _param_lock: Lock = None

    def __init__(self, intensity_controller: IntensityController) -> None:
        self.current_vibration = 0.0
        self.ambient_vibration = 0.10
        self.ambient_vibration_variance = 0.05
        self.ambient_vibration_change_rate = 3.0
        self.ambient_vibration_change_rate_variance = 0.5
        self.computed_change_rate = self.ambient_vibration_change_rate
        self.computed_ambient_vibration = self.ambient_vibration
        self.last_change_time = time.time()

        self._param_lock = Lock()
        self._stop_flag = False
        self._running = False
        self.intensity_controller = intensity_controller
        self.actor = Thread(
            target=self.settle_ambience,
            name="Ambient Vibration Controller Thread",
            daemon=True,
        )

    def start(self) -> None:
        self.actor.start()
        self._running = True

    def stop(self, *, timeout: float = 1.0) -> None:
        """
        Will set the stop flag, and try and join the actor thread.
        Has a 1s timeout by default.

        :return: None
        """
        self._stop_flag = True
        self.actor.join(timeout)

    def force_stop(self) -> None:
        """
        The actor in this class is a Daemon, it is safe to just ignore it.
        :return: None
        """
        self._stop_flag = True

    def update_parameters(self, kill_streak: int, death_streak: int) -> None:
        with self._param_lock:
            self.ambient_vibration = max(
                interpolate_value_bounded(
                    float(kill_streak), 0.0, 15.0, 0.1, 0.6
                ),
                interpolate_value_bounded(
                    float(death_streak), 0.0, 5.0, 0.1, 0.6
                )
            )
            self.ambient_vibration_variance = max(
                interpolate_value_bounded(
                    float(kill_streak), 0.0, 15.0, 0.05, 0.33
                ),
                interpolate_value_bounded(
                    float(death_streak), 0.0, 5.0, 0.05, 0.33
                )
            )
            self.ambient_vibration_change_rate = min(
                interpolate_value_bounded(
                    float(kill_streak), 0.0, 15.0, 6.9, 2.5
                ),
                interpolate_value_bounded(
                    float(death_streak), 0.0, 5.0, 6.9, 3.1
                )
            )
            self.ambient_vibration_change_rate_variance = min(
                interpolate_value_bounded(
                    float(kill_streak), 0.0, 15.0, 0.5, 0.2
                ),
                interpolate_value_bounded(
                    float(death_streak), 0.0, 5.0, 0.5, 0.3
                )
            )

    def settle_ambience(self) -> None:
        while not self._stop_flag:
            time.sleep(0.05)
            _now = time.time()
            if _now - self.last_change_time > self.computed_change_rate:
                if not self.intensity_controller.is_running():
                    print("Intensity controller thread is not running, cannot control ambience.")
                    break

                with self._param_lock:
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

                self.computed_change_rate = _new_change_rate
                self.last_change_time = _now
                _slider = ValueSlider(
                    self.intensity_controller.get_ambient_intensity(),
                    _new_ambient_intensity,
                    500.0,
                    self.intensity_controller.set_ambient_intensity
                )
                self.intensity_controller.set_ambient_intensity_slider(_slider)
        print("Exiting ambience control thread...")


class Vibrator(metaclass=Singleton):
    client: Client = None
    connector: WebsocketConnector = None
    devices: list[Device] = None
    intensity_controller: IntensityController = None
    ambient_intensity_controller: AmbienceController = None
    # Instantaneous vibrations
    current_vibration: float = None

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
        self.intensity_controller = IntensityController(self.set_combined_intensity)
        self.ambient_intensity_controller = AmbienceController(self.intensity_controller)

    def start(self) -> None:
        rprint("[italics bright_black]Starting core controller...[/italics bright_black]")
        self.intensity_controller.start()
        time.sleep(0.2)
        rprint("[italics bright_black]Starting ambient controller...[/italics bright_black]")
        self.ambient_intensity_controller.start()

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

    def set_device(self):
        self.devices = list(self.client.devices.values())

    def set_combined_intensity(self, intensity: float) -> None:
        self.current_vibration = intensity

    async def issue_command(self):
        """
        Sets all actuators in all devices to the given intensity
        """
        if not self.client.connected:
            print("Tried to issue command while 'Not connected'!")
            return

        await self._apply_intensity()

    def apply_instant_intensity(self, initial_intensity: float, duration: float) -> None:
        _slider = ValueSlider(
            initial_intensity,
            0.0,
            duration,
            self.intensity_controller.set_instant_intensity
        )
        self.intensity_controller.set_instant_intensity_slider(_slider, inherit_starting=False, inherit_ending=True)

    async def check_connection(self) -> None:
        if not self.client.connected:
            await self.client.connect(self.connector)

    async def stop_all(self) -> None:
        self.ambient_intensity_controller.stop()
        self.intensity_controller.stop()
        await self.client.disconnect()


def abort(signum, frame):
    print("Received exit signal, ending...")
    _vibe = Vibrator()
    loop = get_running_loop()
    loop.create_task(_vibe.stop_all())
    print("Killed vibrator component")

    _inst = SSEListener(event_endpoint=None)
    if _inst.t_subscriber is not None:
        _inst.shutdown_flag = True
        _inst.t_subscriber.join(timeout=2.0)
    print("Killed SSE Listener...")
    exit(0)


def interaction_pane(output_queue: Queue):
    while input("Type 'exit' at any time to exit program.\n").lower() != "exit":
        time.sleep(0.05)

    rprint("[italic red]Exiting program...[/italic red]")
    output_queue.put(True)


async def main():
    _vibe = Vibrator(ws_host="localhost")
    await _vibe.connect_and_scan()
    _vibe.set_device()

    _name = input("Enter your in-game name as it appears >")
    _steam_id = input("Enter your steam ID64 (it should look something like 76561198071482715) >")

    # TODO: make this parameterized / pulled from MAC
    _player_tracker = PlayerTracker(_name, _steam_id)
    _sse_listener = SSEListener.with_mac()

    _last_time = time.time() * 1000
    _time_elapsed: float = 0.0

    rprint("[italic green]Starting vibrator...[/italic green]")
    _vibe.start()
    _flag_q: Queue = Queue()
    _stop_flag: bool = False
    _thread = Thread(
        target=interaction_pane,
        name="IO Control thread",
        args=(_flag_q,)
    )
    _thread.start()

    while not _stop_flag:
        await _vibe.check_connection()
        if not _sse_listener.q_subscriber.empty():
            event = cast(Union[KillEvent, ChatEvent], _sse_listener.q_subscriber.get())
            _ks: Optional[int] = None
            _ds: Optional[int] = None
            _updates: list[UpdateTypes]
            if isinstance(event, ChatEvent):
                _updates = _player_tracker.handle_chat_message(event)
                if len(_updates) > 0:
                    rprint(f"[italic bright_black]Notable Chat Event: {event}[/italic bright_black]")
                for update in _updates:
                    match update:
                        case UpdateTypes.CHAT_YOU_SAID_UWU:
                            rprint("[bold bright_yellow]YOU SAID UWU/OWO -> GET VIBED[/bold bright_yellow]")
                            _vibe.apply_instant_intensity(0.4, 750.0)
                        case UpdateTypes.CHAT_FUCK_YOU:
                            rprint("[bold indian_red]SOMEONES ANGRY -> MMM BZZZZZZ[/bold indian_red]")
                            _vibe.apply_instant_intensity(0.3, 500.0)

            elif isinstance(event, KillEvent):
                _ks, _ds, _updates = _player_tracker.add_kill_event(event)
                _vibe.ambient_intensity_controller.update_parameters(_ks, _ds)

                if len(_updates) > 0:
                    rprint(f"[italic bright_black]{_player_tracker.player_name} kill streak: {_ks}, "
                           f"death streak: {_ds}[/italic bright_black]")

                for update in _updates:
                    match update:
                        case UpdateTypes.GOT_KILLED:
                            rprint("[bold indian_red]OH NO, YOU DIED -> *VIBRATES IN YOU*[/bold indian_red]")
                            _vibe.apply_instant_intensity(0.4, 666.0)
                        case UpdateTypes.KILLED_ENEMY:
                            rprint("[bold green_yellow]GOOD GIRL/BOY/PUPPY/KITTY -> HAVE A REWARD[/bold green_yellow]")
                            _vibe.apply_instant_intensity(0.45, 750.0)
                        case UpdateTypes.CRIT_KILLED_ENEMY:
                            rprint("[bold aquamarine1]FAIR AND BALANCED, BITCH! -> *GIBS YOU*[/bold aquamarine1]")
                            _vibe.apply_instant_intensity(0.6, 850.0)
                        case UpdateTypes.GOT_CRIT_KILLED:
                            rprint("[bold dark_orange3]LOL NOOB EZ -> *TOUCHES UR PROSTATE*[/bold dark_orange3]")
                            _vibe.apply_instant_intensity(0.65, 1200.0)

        await _vibe.issue_command()
        try:
            _value = _flag_q.get(block=False)
            if isinstance(_value, bool) and _value:
                _stop_flag = _value
        except queue.Empty:
            pass

    _thread.join()
    _vibe = Vibrator()
    rprint("[italic yellow]Attempting stop of all vibrator components...[/italic yellow]")
    asyncio.ensure_future(_vibe.stop_all(), loop=get_running_loop())
    rprint("[italic green]Killed vibrator component...[/italic green]")

    rprint("[italic yellow]Awaiting soft exit of SSEListener (will force exit after 2s)...[/italic yellow]")
    _inst = SSEListener(event_endpoint=None)
    if _inst.t_subscriber is not None:
        _inst.shutdown_flag = True
        _inst.t_subscriber.join(timeout=2.0)
    rprint("[italic green]Killed SSE Listener...[/italic green]")
    rprint("[italic green]Vibe Controller Exiting...[/italic green]")


if __name__ == "__main__":
    signal(SIGINT, abort)
    run(main())
