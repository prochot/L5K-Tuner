# main.py
# Copyright (c) 2025 Alex Prochot
#
# Application entry point launching the L5K Processor GUI.
"""Application entry point for the L5K Processor GUI."""


import sys
import pathlib
import tkinter as tk
from tkinter import ttk

# Support running both as a package (`python -m L5KTuner.main`)
# and directly as a script (`python L5KTuner/main.py`).
if __package__:
    from .gui import L5KTunerApp
    from .utils import configure_logging
else:  # pragma: no cover - convenience for direct invocation
    sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
    from L5KTuner.gui import L5KTunerApp  # type: ignore
    from L5KTuner.utils import configure_logging  # type: ignore

def main():
    """
    Main function to initialize and run the application.
    """
    configure_logging()
    root = tk.Tk()
    
    base_dir = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent.parent))
    icon_path = base_dir / "assets" / "app-icon.ico"
    if icon_path.exists():
        root.iconbitmap(default=str(icon_path))

    # Optional: Apply a modern theme
    # style = ttk.Style(root)
    # style.theme_use('equilux')
    
    app = L5KTunerApp(root)
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        root.after(0, lambda: app.open_project_file(file_path))
    root.mainloop()

if __name__ == '__main__':
    main()
