__all__ = ['run_app']
__name__ = "MAC Toys"
__author__ = "Lilith"
from asyncio import run
from .config import Config
from .vibrator import main, __version__


def run_app():
    print("Loading configuration file...")
    _config = Config()
    print(f"Running {__author__}'s {__name__} app version {__version__}...")
    run(main(_config))
