# Changelog

## Unreleased
- (none)

## 0.1.1 - 2026-01-18
- Added dirty tracking with save prompts on close/open/import and a title-bar indicator.
- Auto-maximizes the window on small screens (1024x768 or smaller).
- Logging now writes to the user Documents folder and the log viewer shows the full path.
- Updated Windows packaging: new app/file icons and installer notes.

## 0.1.0 - 2025-12-07
- Added structured tree state (`TreeState`) with filtering helpers and persisted checkbox state; View menu supports enabled/disabled/all filters.
- Introduced project save/load (`.l5kproj`) independent of the original `.l5k`; restored checkbox states and status-bar/title updates.
- Added merge preview for updated `.l5k` files with selectable additions/removals.
- Split utilities into dedicated modules (`strings.py`, `patterns.py`, `utils.py`, `exporter.py`, `types.py`, `tree_state.py`, `view_filter.py`).
- Refactored parser state machines (`ParseState`, `ExportState`, `TagBuffer`), extracted regex patterns, and added micro-optimizations.
- GUI enhancements: File/View/Help menus, log viewer, status bar and title updates, selection control enable/disable, include/exclude buttons, file name display.
- Logging improvements: standardized logging and action logs for import/export/open/save/close/merge.
- Added tests for AOI base-type correction, program tags, export features, filtering/persistence, tree state round-trips, and project JSON round-trip (GUI and no-GUI).
- Built pyinstaller exe L5KTuner.exe
