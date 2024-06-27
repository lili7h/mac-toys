from __future__ import annotations

import time
from threading import Lock, Thread
from random import uniform
from mac_toys.interpolation import ValueSlider
from mac_toys.helpers import interpolate_value_bounded, prnt
from mac_toys.thread_manager import ThreadedActor
from mac_toys.vibration.intensity import IntensityController
from mac_toys.config import Config


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
    _config: Config = None
    # update lock
    _param_lock: Lock = None
    # configured values store
    # Ambient Vibration Intensity config values
    _avi_kill_min: float = None
    _avi_kill_max: float = None
    _avi_death_min: float = None
    _avi_death_max: float = None
    # Target kill and deathstreak values
    _max_ks_value: float = None
    _max_ds_value: float = None
    # Ambient Vibration Variance values
    _avv_kill_min: float = None
    _avv_kill_max: float = None
    _avv_death_min: float = None
    _avv_death_max: float = None
    # Ambient Vibration Change Rate values
    _avcr_kill_max: float = None
    _avcr_kill_min: float = None
    _avcr_death_max: float = None
    _avcr_death_min: float = None
    # Ambient Vibration Change Rate Variance values
    _avcrv_kill_max: float = None
    _avcrv_kill_min: float = None
    _avcrv_death_max: float = None
    _avcrv_death_min: float = None



    def __init__(
            self,
            intensity_controller: IntensityController,
            config: Config
    ) -> None:
        self.current_vibration = 0.0
        self.ambient_vibration = 0.10
        self.ambient_vibration_variance = 0.05
        self.ambient_vibration_change_rate = 3.0
        self.ambient_vibration_change_rate_variance = 0.5
        self.computed_change_rate = self.ambient_vibration_change_rate
        self.computed_ambient_vibration = self.ambient_vibration
        self.last_change_time = time.time()

        self._config = config
        self._param_lock = Lock()
        self._stop_flag = False
        self._running = False
        self.intensity_controller = intensity_controller
        self.actor = Thread(
            target=self.settle_ambience,
            name="Ambient Vibration Controller Thread",
            daemon=True,
        )

        # I'm lazy so im loading configs this way, #deal
        self._avi_kill_min = self._config.ambience_intensity('killstreak_minimum')
        self._avi_kill_max = self._config.ambience_intensity('killstreak_maximum')
        self._avi_death_min = self._config.ambience_intensity('deathstreak_minimum')
        self._avi_death_max = self._config.ambience_intensity('deathstreak_maximum')
        self._max_ks_value = float(self._config.ambience_max_at_value('killstreak'))
        self._max_ds_value = float(self._config.ambience_max_at_value('deathstreak'))
        self._avv_kill_min = self._config.ambience_intensity_variance('killstreak_minimum')
        self._avv_kill_max = self._config.ambience_intensity_variance('killstreak_maximum')
        self._avv_death_min = self._config.ambience_intensity('deathstreak_minimum')
        self._avv_death_max = self._config.ambience_intensity('deathstreak_maximum')
        self._avcr_kill_max = self._config.ambience_change_rate('killstreak_maximum')
        self._avcr_kill_min = self._config.ambience_change_rate('killstreak_minimum')
        self._avcr_death_max = self._config.ambience_change_rate('deathstreak_maximum')
        self._avcr_death_min = self._config.ambience_change_rate('deathstreak_minimum')
        self._avcrv_kill_max = self._config.ambience_change_rate_variance('killstreak_maximum')
        self._avcrv_kill_min = self._config.ambience_change_rate_variance('killstreak_minimum')
        self._avcrv_death_max = self._config.ambience_change_rate_variance('deathstreak_maximum')
        self._avcrv_death_min = self._config.ambience_change_rate_variance('deathstreak_minimum')
        self._slide_time = self._config.ambience_transition_time()


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
        with (self._param_lock):

            self.ambient_vibration = max(
                interpolate_value_bounded(
                    float(kill_streak), 0.0, self._max_ks_value, self._avi_kill_min, self._avi_kill_max
                ),
                interpolate_value_bounded(
                    float(death_streak), 0.0, self._max_ds_value, self._avi_death_min, self._avi_death_max
                )
            )
            self.ambient_vibration_variance = max(
                interpolate_value_bounded(
                    float(kill_streak), 0.0, self._max_ks_value, self._avv_kill_min, self._avv_kill_max
                ),
                interpolate_value_bounded(
                    float(death_streak), 0.0, self._max_ds_value, self._avv_death_min, self._avv_death_max
                )
            )
            self.ambient_vibration_change_rate = min(
                interpolate_value_bounded(
                    float(kill_streak), 0.0, self._max_ks_value, self._avcr_kill_max, self._avcr_kill_min
                ),
                interpolate_value_bounded(
                    float(death_streak), 0.0, self._max_ds_value, self._avcr_death_max, self._avcr_death_min
                )
            )
            self.ambient_vibration_change_rate_variance = min(
                interpolate_value_bounded(
                    float(kill_streak), 0.0, self._max_ks_value, self._avcrv_kill_max, self._avcrv_kill_min
                ),
                interpolate_value_bounded(
                    float(death_streak), 0.0, self._max_ds_value, self._avcrv_death_max, self._avcrv_death_min
                )
            )

    def settle_ambience(self) -> None:
        while not self._stop_flag:
            time.sleep(0.05)
            _now = time.time()
            if _now - self.last_change_time > self.computed_change_rate:
                if not self.intensity_controller.is_running():
                    prnt("Intensity controller thread is not running, cannot control ambience.")
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
                    self._slide_time,
                    self.intensity_controller.set_ambient_intensity
                )
                self.intensity_controller.set_ambient_intensity_slider(_slider)
        prnt("Exiting ambience control thread...")
