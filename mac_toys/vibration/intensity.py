import time

from threading import Thread
from typing import Callable
from asyncio import get_running_loop, set_event_loop, new_event_loop

from mac_toys.interpolation import ValueSlider
from mac_toys.thread_manager import ThreadedActor


class IntensityController(ThreadedActor):
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

    def stop(self, *, timeout: float = 1.0) -> None:
        self._running = False
        self._applicator_thread.join(timeout)

    def force_stop(self) -> None:
        self._running = False

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
    ) -> None:
        _ending = 0.0
        if self.instant_intensity_slider is not None:
            if self.instant_intensity_slider.complete:
                self.instant_intensity_slider.join()
            else:
                self.instant_intensity_slider.cancel()

        if inherit_starting:
            slider.starting_value = self._combined_intensity
        else:
            slider.starting_value += min(0.99, self._combined_intensity)

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

