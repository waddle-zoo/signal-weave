"""Executable entry point; kept outside the library import path."""

from multiprocessing import freeze_support

from signalweave.cli import main

if __name__ == "__main__":
    freeze_support()
    main()
