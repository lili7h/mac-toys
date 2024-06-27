from pathlib import Path
from typing import Literal

import toml

from mac_toys.sse_listener import Singleton
from mac_toys.tracker import UpdateTypes


class Config(metaclass=Singleton):
    CONFIG_PATH: Path = None
    _configs: dict = None

    def __init__(self, path: Path = Path("./config.toml")) -> None:
        self.CONFIG_PATH = path
        self._configs = toml.load(self.CONFIG_PATH)

    def config(self) -> dict:
        return self._configs

    @staticmethod
    def _parse_update_types(update_type_enum: UpdateTypes) -> str:
        match update_type_enum:
            case UpdateTypes.GOT_CRIT_KILLED:
                return 'on_crit_death'
            case UpdateTypes.CRIT_KILLED_ENEMY:
                return 'on_crit_kill'
            case UpdateTypes.KILLED_ENEMY:
                return 'on_kill'
            case UpdateTypes.GOT_KILLED:
                return 'on_death'
            case UpdateTypes.CHAT_ANY_SAY:
                return 'on_any_chat_msg'
            case UpdateTypes.CHAT_YOU_SAY:
                return 'on_you_chat_msg'
            case UpdateTypes.DOMINATED_ENEMY:
                return 'on_domination'
            case UpdateTypes.REMOVED_DOMINATION:
                return 'on_undominated'
            case UpdateTypes.LOST_DOMINATION:
                return 'on_lost_domination'
            case UpdateTypes.GOT_DOMINATED:
                return 'on_dominated'
            case _:
                return 'on_kill'

    def instant_intensity(
            self,
            key: Literal[
                'on_death', 'on_kill', 'on_crit_kill', 'on_crit_death', 'on_you_chat_msg', 'on_any_chat_msg',
                'on_domination', 'on_undominated', 'on_lost_domination', 'on_dominated',
            ] | UpdateTypes
    ) -> float:
        _key = Config._parse_update_types(key) if isinstance(key, UpdateTypes) else key

        return self._configs['instant']['intensity'][_key]

    def instant_times(
            self,
            key: Literal[
                'on_death', 'on_kill', 'on_crit_kill', 'on_crit_death', 'on_you_chat_msg', 'on_any_chat_msg',
                'on_domination', 'on_undominated', 'on_lost_domination', 'on_dominated',
            ] | UpdateTypes
    ) -> int:
        _key = Config._parse_update_types(key) if isinstance(key, UpdateTypes) else key

        return self._configs['instant']['times'][_key]

    def instant_chat_messages(
            self,
            key: Literal[
                'trigger_on_you_say', 'trigger_on_any_say'
            ]
    ) -> list[str]:
        return self._configs['instant']['chat_messages'][key]

    def ambience_transition_time(self) -> int:
        return self._configs['ambience']['transition_time']

    def ambience_max_at_value(
            self,
            key: Literal[
                'killstreak', 'deathstreak'
            ]
    ) -> int:
        return self._configs['ambience']['max_at_value'][key]

    def ambience_intensity(
            self,
            key: Literal[
                'killstreak_minimum', 'killstreak_maximum', 'deathstreak_minimum', 'deathstreak_maximum'
            ]
    ) -> float:
        return self._configs['ambience']['intensity'][key]

    def ambience_intensity_variance(
            self,
            key: Literal[
                'killstreak_minimum', 'killstreak_maximum', 'deathstreak_minimum', 'deathstreak_maximum'
            ]
    ) -> float:
        return self._configs['ambience']['intensity_variance'][key]

    def ambience_change_rate(
            self,
            key: Literal[
                'killstreak_minimum', 'killstreak_maximum', 'deathstreak_minimum', 'deathstreak_maximum'
            ]
    ) -> float:
        return self._configs['ambience']['change_rate'][key]

    def ambience_change_rate_variance(
            self,
            key: Literal[
                'killstreak_minimum', 'killstreak_maximum', 'deathstreak_minimum', 'deathstreak_maximum'
            ]
    ) -> float:
        return self._configs['ambience']['change_rate_variance'][key]


if __name__ == "__main__":
    _conf = Config(Path("../config.toml"))
    _config = _conf.config()

    print(_conf.instant_intensity('on_kill'))
