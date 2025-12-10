# L5K Tuner

GUI tool for importing Rockwell Logix `.l5k` files, inspecting and pruning tags/UDTs/AOIs/program tags, and exporting filtered content. Supports saving/loading project state (`.l5kproj`), merge previews for updated L5K files, and basic logging.

## Features
- Import `.l5k` files and display header, UDTs, AOIs, controller tags, and program tags in a tree with include/exclude controls.
- Export a filtered `.l5k` based on current selections.
- Save/Load project state to `.l5kproj` (restores selections and descriptions without needing the original `.l5k`).
- Merge updated `.l5k` files with a preview and per-item add/remove selection.
- View filters: show all, enabled-only, or disabled-only items.
- Log viewer (Help → Show Log) and status/title updates that reflect the current file.

## Requirements
- Python 3.12+

## Installation
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

## Running
```bash
python -m L5KTuner.main
```

## Usage
- File → Import (or “Import L5K” button): load an `.l5k` file.
- Inspect the tree and toggle inclusion with the right-panel checkbox or the Include/Exclude buttons.
- File → Export: write a filtered `.l5k` with only selected items.
- File → Save / Save As: save project state to `.l5kproj` (includes selections/descriptions).
- File → Open: reload a saved `.l5kproj` without the original `.l5k`.
- File → Merge Updated L5K: preview differences against the current project and choose which additions/removals to apply.
- View → Show: filter the tree (all/enabled/disabled).
- Help → Show Log: open the log viewer.

## Testing
Run the test suite from the repo root:
```bash
pytest
```
Tk-dependent tests auto-skip if Tk is unavailable.

## Project layout
- `L5KTuner/`: parser (`l5k_parser.py`), GUI (`gui.py`), domain models (`models.py`), helpers (`strings.py`, `patterns.py`, `utils.py`, `exporter.py`, `tree_state.py`, `view_filter.py`, `l5k_types.py`).
- `data/`: sample `.L5K` files.
- `tests/`: parsing/export/filtering/persistence tests.

## Logging
- Logs to `l5k_processor.log` in the repo root when running the app.

## License
MIT License (see `LICENSE`).
