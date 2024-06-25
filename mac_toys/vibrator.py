from __future__ import annotations

__version__ = "0.1.0a"

import asyncio
import queue
import time

from asyncio import sleep, run, get_running_loop
from threading import Thread
from queue import Queue
from signal import signal, SIGINT
from typing import Union, cast, Optional

from buttplug import Client, WebsocketConnector, ProtocolSpec, Device, DisconnectedError
from tqdm import tqdm

from mac_toys.helpers import prnt
from mac_toys.sse_listener import SSEListener, ChatEvent, KillEvent, Singleton
from mac_toys.tracker import PlayerTracker, UpdateTypes
from mac_toys.thread_manager import Agent
from mac_toys.interpolation import ValueSlider

from mac_toys.vibration.ambience import AmbienceController
from mac_toys.vibration.intensity import IntensityController


class Vibrator(metaclass=Singleton):
    client: Client = None
    connector: WebsocketConnector = None
    # Cache the devices one layer up rather than having to reach into the client every time
    devices: list[Device] = None
    # This agent controls all the ThreadedActors that the Vibrator class instantiates
    agent: Agent = None
    # Current intensity value (inclusive of ambient and instant)
    current_vibration: float = None
    # intensity status bar
    pbar: tqdm = None

    async def connect_and_scan(self) -> None:
        assert self.connector is not None

        # If this succeeds, we'll be connected. If not, we'll probably have some
        # sort of exception thrown of type ButtplugError.
        try:
            await self.client.connect(self.connector)
        except Exception as e:
            prnt(f"Could not connect to server, exiting: {e}")
            return

        if len(self.client.devices) == 0:
            prnt(f"Scanning for devices now, see you in 10s!")
            await self.client.start_scanning()
            await sleep(10)
            await self.client.stop_scanning()
            prnt(f"Done.")
        else:
            prnt(f"Found devices connected, assuming no scan needed.")

        if len(self.client.devices) > 0:
            prnt(f"Found {len(self.client.devices)} devices!")
        else:
            prnt(f"Found no devices :(")

    def __init__(self, ws_host: str = "127.0.0.1", port: int = 12345):
        self.client = Client("MAC Toys Client", ProtocolSpec.v3)
        self.connector = WebsocketConnector(f"ws://{ws_host}:{port}")
        self.agent = Agent()
        self.agent.add_agent(
            "INTCON", IntensityController(self.set_combined_intensity)
        ).add_agent(
            "AMBINTCON", AmbienceController(cast(IntensityController, self.agent.get_agent('INTCON')))
        )

    def start(self) -> None:
        prnt("Starting controllers...")
        self.agent.start_all()
        self.pbar = tqdm(total=100, desc="Intensity", dynamic_ncols=True, bar_format='{l_bar}{bar}')

    async def _apply_intensity(self) -> None:
        futures = []
        for dev in self.devices:
            for r_act in dev.actuators:
                futures.append(r_act.command(self.current_vibration))
        try:
            async with asyncio.timeout(0.5):
                await asyncio.gather(*futures, return_exceptions=True)
        except DisconnectedError:
            prnt("Disconnected")
        except TimeoutError:
            prnt("Timed-out")

    def set_device(self):
        self.devices = list(self.client.devices.values())

    def set_combined_intensity(self, intensity: float) -> None:
        self.current_vibration = intensity

    async def issue_command(self):
        """
        Sets all actuators in all devices to the given intensity
        """
        if not self.client.connected:
            prnt("Tried to issue command while 'Not connected'!")
            return

        if self.current_vibration is not None:
            _new_n = round(self.current_vibration * 100)
            if _new_n != self.pbar.n:
                self.pbar.update(int(_new_n - self.pbar.n))
                self.pbar.display()

            await self._apply_intensity()

    def apply_instant_intensity(self, initial_intensity: float, duration: float) -> None:
        _inten_controller = cast(IntensityController, self.agent.get_agent('INTCON'))
        _slider = ValueSlider(
            initial_intensity,
            0,
            duration,
            _inten_controller.set_instant_intensity
        )
        _inten_controller.set_instant_intensity_slider(_slider, inherit_starting=False)

    async def check_connection(self) -> None:
        if not self.client.connected:
            await self.client.connect(self.connector)

    async def stop_all(self) -> None:
        self.pbar.close()
        self.pbar.clear()
        self.agent.stop_all()
        await self.client.disconnect()


def abort(signum, frame):
    prnt("Received exit signal, ending...")
    _vibe = Vibrator()
    loop = get_running_loop()
    loop.create_task(_vibe.stop_all())
    prnt("Killed vibrator component")

    _inst = SSEListener(event_endpoint=None)
    if _inst.t_subscriber is not None:
        _inst.shutdown_flag = True
        _inst.t_subscriber.join(timeout=2.0)
    prnt("Killed SSE Listener...")
    exit(0)


def interaction_pane(output_queue: Queue):
    prnt("Type 'exit' at any time to exit program (the intensity bar will break, ignore it).\n")
    while input().lower() != "exit":
        time.sleep(0.05)
        prnt("Type 'exit' at any time to exit program (the intensity bar will break, ignore it).\n")

    prnt("Exiting program...")
    output_queue.put(True)


async def main():
    _vibe = Vibrator(ws_host="localhost")
    await _vibe.connect_and_scan()
    _vibe.set_device()

    _name = input("Enter your in-game name as it appears > ")
    _steam_id = input("Enter your steam ID64 (it should look something like 76561198071482715) > ")

    # TODO: make this parameterized / pulled from MAC
    _player_tracker = PlayerTracker(_name, _steam_id)
    _sse_listener = SSEListener.with_mac()

    _last_time = time.time() * 1000
    _time_elapsed: float = 0.0

    prnt("Starting vibrator...")
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
                for update in _updates:
                    match update:
                        case UpdateTypes.CHAT_YOU_SAID_UWU:
                            prnt("YOU SAID UWU/OWO -> GET VIBED")
                            _vibe.apply_instant_intensity(0.4, 750.0)
                        case UpdateTypes.CHAT_FUCK_YOU:
                            prnt("SOMEONES ANGRY -> MMM BZZZZZZ")
                            _vibe.apply_instant_intensity(0.3, 500.0)

            elif isinstance(event, KillEvent):
                _ks, _ds, _updates = _player_tracker.add_kill_event(event)
                cast(AmbienceController, _vibe.agent.get_agent('AMBINTCON')).update_parameters(_ks, _ds)

                for update in _updates:
                    match update:
                        case UpdateTypes.GOT_KILLED:
                            prnt("OH NO, YOU DIED -> *VIBRATES IN YOU*")
                            _vibe.apply_instant_intensity(0.4, 666.0)
                        case UpdateTypes.KILLED_ENEMY:
                            prnt("GOOD GIRL/BOY/PUPPY/KITTY -> HAVE A REWARD")
                            _vibe.apply_instant_intensity(0.45, 750.0)
                        case UpdateTypes.CRIT_KILLED_ENEMY:
                            prnt("FAIR AND BALANCED, BITCH! -> *GIBS YOU*")
                            _vibe.apply_instant_intensity(0.6, 850.0)
                        case UpdateTypes.GOT_CRIT_KILLED:
                            prnt("LOL NOOB EZ -> *TOUCHES UR PROSTATE*")
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
    prnt("Attempting stop of all vibrator components...")
    asyncio.ensure_future(_vibe.stop_all(), loop=get_running_loop())
    prnt("Killed vibrator component...")

    prnt("Awaiting soft exit of SSEListener (will force exit after 2s)...")
    _inst = SSEListener(event_endpoint=None)
    if _inst.t_subscriber is not None:
        _inst.shutdown_flag = True
        _inst.t_subscriber.join(timeout=2.0)
    prnt("Killed SSE Listener...")
    prnt("Vibe Controller Exiting...")


if __name__ == "__main__":
    signal(SIGINT, abort)
    run(main())
