from typing import Union, cast
from signal import signal, SIGINT
from mac_toys.sse_listener import SSEListener, KillEvent, ChatEvent


def abort(signum, frame):
    print("Received exit signal, ending...")
    _inst = SSEListener(event_endpoint=None)
    if _inst.t_subscriber is not None:
        _inst.shutdown_flag = True
        _inst.t_subscriber.join()
    exit(0)


def main() -> None:
    print("INFO: Starting")
    instance = SSEListener.with_mac()
    while True:
        if not instance.q_subscriber.empty():
            event = cast(Union[KillEvent | ChatEvent], instance.q_subscriber.get())
            if isinstance(event, ChatEvent):
                print(f"Chat: {event}")
            elif isinstance(event, KillEvent):
                print(f"Kill: {event}")


if __name__ == "__main__":
    signal(SIGINT, abort)
    main()
