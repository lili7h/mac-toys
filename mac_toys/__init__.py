__all__ = ['run_app']
__name__ = "MAC Toys"
__author__ = "Lilith"
from asyncio import run
from .vibrator import main, __version__


def run_app():
    print(f"Running {__author__}'s {__name__} app version {__version__}...")
    run(main())
