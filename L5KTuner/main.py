# main.py
# Copyright (c) 2025 Alex Prochot
#
# Application entry point launching the L5K Processor GUI.
"""Application entry point for the L5K Processor GUI."""


import sys
import pathlib
import tkinter as tk
from tkinter import ttk
import logging

# Support running both as a package (`python -m L5KTuner.main`)
# and directly as a script (`python L5KTuner/main.py`).
if __package__:
    from .gui import L5KTunerApp
else:  # pragma: no cover - convenience for direct invocation
    sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
    from L5KTuner.gui import L5KTunerApp  # type: ignore

def main():
    """
    Main function to initialize and run the application.
    """
    if not logging.getLogger().handlers:
        logging.basicConfig(
            filename="l5k_tuner.log",
            level=logging.INFO,
            format="%(asctime)s - %(message)s",
            filemode="w",
        )
    root = tk.Tk()
    
    # Optional: Apply a modern theme
    # style = ttk.Style(root)
    # style.theme_use('equilux')
    
    app = L5KTunerApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()
