from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, auto
from threading import Thread


class ThreadedActor(ABC):
    _actor: Thread = None

    @property
    def actor(self) -> Thread:
        return self._actor

    @actor.setter
    def actor(self, actor: Thread) -> None:
        self._actor = actor

    @abstractmethod
    def start(self) -> None:
        pass

    @abstractmethod
    def stop(self, *, timeout: float = 1.0) -> None:
        pass

    @abstractmethod
    def force_stop(self) -> None:
        pass


class ActorState(Enum):
    NOT_STARTED = auto()
    RUNNING = auto()
    STOPPED = auto()


class Agent:
    _last_added: dict[str, ActorState | ThreadedActor] = None
    actors: dict[str, dict[str, ActorState | ThreadedActor]] = None

    def __init__(self) -> None:
        self.actors = {}

    def add_agent(self, name: str, actor: ThreadedActor) -> Agent:
        if name in self.actors:
            _state = self.actors[name].get('state')
            _actor = self.actors[name].get('actor')
            if _state == ActorState.RUNNING:
                _actor.stop()

        self.actors[name] = {
            'state': ActorState.NOT_STARTED,
            'actor': actor
        }
        self._last_added = self.actors[name]

        return self

    def start(self, actor_name: str = None) -> None:
        if actor_name is None:
            _state = self._last_added.get('state')
            _actor = self._last_added.get('actor')
            if _state != ActorState.NOT_STARTED:
                raise ValueError(f"Last added actor is already started.")

            _actor.start()
            self._last_added['state'] = ActorState.RUNNING
        else:
            _actor_d = self.actors.get(actor_name)
            if _actor_d:
                _state = _actor_d.get('state')
                _actor = _actor_d.get('actor')

                if _state != ActorState.NOT_STARTED:
                    raise ValueError(f"Actor '{actor_name}' is already started.")

                _actor.start()
                _actor_d['state'] = ActorState.RUNNING
            else:
                raise KeyError(f"Actor of name '{actor_name}' does not exist.")

    def stop(self, actor_name: str) -> None:
        _actor_d = self.actors.get(actor_name)
        if _actor_d:
            _state = _actor_d.get('state')
            _actor = _actor_d.get('actor')

            if _state != ActorState.RUNNING:
                raise ValueError(f"Actor '{actor_name}' is already stopped/not started.")

            _actor.stop()
            _actor_d['state'] = ActorState.STOPPED
        else:
            raise KeyError(f"Actor of name '{actor_name}' does not exist.")

    def start_all(self) -> None:
        for thread_name in self.actors:
            _state = self.actors[thread_name].get('state')
            _actor = self.actors[thread_name].get('actor')
            match _state:
                case ActorState.NOT_STARTED:
                    _actor.start()
                    self.actors[thread_name]['state'] = ActorState.RUNNING
                case _:
                    pass

    def stop_all(self) -> None:
        for thread_name in self.actors:
            _state = self.actors[thread_name].get('state')
            _actor = self.actors[thread_name].get('actor')
            match _state:
                case ActorState.RUNNING:
                    _actor.stop()
                    self.actors[thread_name]['state'] = ActorState.STOPPED
                case _:
                    pass

    def get_agent(self, name: str) -> ThreadedActor:
        if name not in self.actors:
            raise KeyError("That actor is not in the Agent.")

        return self.actors[name]['actor']
