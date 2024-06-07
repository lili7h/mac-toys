from enum import Enum, auto
from mac_toys.sse_listener import Singleton, KillEvent, ChatEvent


SAFE_WORD_STOP: str = "PLUG STOP"


class UpdateTypes(Enum):
    # Related to kill events
    KILLED_ENEMY = auto()
    DOMINATED_ENEMY = auto()
    CRIT_KILLED_ENEMY = auto()
    GOT_KILLED = auto()
    GOT_DOMINATED = auto()
    GOT_CRIT_KILLED = auto()
    LOST_DOMINATION = auto()
    REMOVED_DOMINATION = auto()
    # Related to chat events
    GOT_MENTIONED = auto()
    CHAT_FUCK_YOU = auto()
    CHAT_YOU_SAID_UWU = auto()
    # Emergency stop chat message
    CHAT_PLAYER_DEMANDED_STOP = auto()


class PlayerTracker(metaclass=Singleton):
    player: str = None
    player_name: str = None
    enemy_kill_tracker: dict[str, int] = None
    dominated_by: list[str] = None
    deaths_by_tracker: dict[str, int] = None
    dominating: list[str] = None
    kill_streak: int = None
    death_streak: int = None

    def handle_chat_message(self, event: ChatEvent) -> list[UpdateTypes]:
        _updates: list[UpdateTypes] = []
        _author = event.author[1]
        if "fuck you" in event.message.lower():
            _updates.append(UpdateTypes.CHAT_FUCK_YOU)

        if _author == self.player:
            # Check if player said uwu/owo (checks whole word match, doesn't include things like 'wowo')
            _words = event.message.lower().split()
            if "uwu" in _words:
                _updates.append(UpdateTypes.CHAT_YOU_SAID_UWU)
            elif "owo" in _words:
                _updates.append(UpdateTypes.CHAT_YOU_SAID_UWU)

            # Let the player drop a safeword in chat for relief
            if event.message.strip() == SAFE_WORD_STOP:
                _updates.append(UpdateTypes.CHAT_PLAYER_DEMANDED_STOP)
        else:
            if self.player_name.lower() in event.message.lower():
                _updates.append(UpdateTypes.GOT_MENTIONED)

        return _updates

    def add_kill_event(self, event: KillEvent) -> tuple[int, int, list[UpdateTypes]]:
        _updates: list[UpdateTypes] = []
        _was_crit = event.crit
        _victim_sid = event.victim[1]
        _killer_sid = event.killer[1]

        # You are the victim of the kill
        if _victim_sid == self.player:
            _updates.append(UpdateTypes.GOT_KILLED)
            if _was_crit:
                _updates.append(UpdateTypes.GOT_CRIT_KILLED)
            # Increment the number of times killed by this person in a row
            if _killer_sid not in self.deaths_by_tracker:
                self.deaths_by_tracker[_killer_sid] = 0
            self.deaths_by_tracker[_killer_sid] += 1

            # Reset domination status towards the enemy, remove from dominating queue if in it
            if _killer_sid in self.enemy_kill_tracker:
                self.enemy_kill_tracker[_victim_sid] = 0
            if _killer_sid in self.dominating:
                self.dominating.remove(_killer_sid)
                _updates.append(UpdateTypes.LOST_DOMINATION)

            # If now getting dominated by this user, add them to the dominated by list
            if self.deaths_by_tracker[_killer_sid] >= 3:
                self.dominated_by.append(_killer_sid)
                _updates.append(UpdateTypes.GOT_DOMINATED)

            # If no kills this life, increase death streak
            if self.kill_streak == 0:
                self.death_streak += 1
            # Reset killstreak
            self.kill_streak = 0
        # You are the person who performed the kill
        elif _killer_sid == self.player:
            _updates.append(UpdateTypes.KILLED_ENEMY)
            if _was_crit:
                _updates.append(UpdateTypes.CRIT_KILLED_ENEMY)
            # Increment killstreak and reset death streak
            self.kill_streak += 1
            self.death_streak = 0

            # Increment number of times you have killed this person in a row
            if _victim_sid not in self.enemy_kill_tracker:
                self.enemy_kill_tracker[_victim_sid] = 0
            self.enemy_kill_tracker[_victim_sid] += 1

            # Reset domination if you are getting dominated by them
            if _victim_sid in self.dominated_by:
                self.dominated_by.remove(_victim_sid)
                _updates.append(UpdateTypes.REMOVED_DOMINATION)
            # Reset times killed in a row by this person
            if _victim_sid in self.deaths_by_tracker:
                self.deaths_by_tracker[_victim_sid] = 0

            # Update domination status of the victim
            if self.enemy_kill_tracker[_victim_sid] >= 3:
                self.dominating.append(_victim_sid)
                _updates.append(UpdateTypes.DOMINATED_ENEMY)

        return self.kill_streak, self.death_streak, _updates

    def __init__(self, name: str, steam_id: str) -> None:
        self.player = steam_id
        self.player_name = name
        self.kill_streak = 0
        self.death_streak = 0
        self.enemy_kill_tracker = {}
        self.dominated_by = []
        self.deaths_by_tracker = {}
        self.dominating = []
