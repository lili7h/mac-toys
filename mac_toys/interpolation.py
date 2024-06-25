from __future__ import annotations

import time
from typing import Callable
from threading import Thread, Lock, get_native_id


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
            if abs(self.target_value - self._current_value) < 0.001 or self._time_remaining < 0:
                self.complete = True
                self._running = False
