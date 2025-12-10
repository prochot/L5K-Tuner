# Known Issues / Limitations

- UDT headers with exotic, nested parentheses inside string literals: balanced-paren tracking works, but rare edge cases could still misplace the first member line.
- UDT member arrays: UI shows `DATA[NN]`, but selection/meta keys use the base name (`DATA`). Searching by the bracketed label won’t match the internal key.
- AOI empty `LOCAL_TAGS`: we always emit an empty block. Some targets may want a minimal stub entry (not emitted today).
- AOI parameters `OF word.bit`: exporter replaces with `: BOOL` for Edge compatibility, losing the bit index by design.
- Attribute passthrough: only Description (and UDT FamilyType) are surfaced; other attributes are preserved only if present in stored definitions. Values are intentionally not exported.
- Tags/values: initial values are omitted by design; models don’t store them.
- Threaded parse UX: load button is disabled during parse, but a close-at-completion race is theoretically possible (guarded, yet worth noting).

# TODO / Future Work

- Export switches: options for (a) emitting a stub `LOCAL_TAGS` entry, (b) preserving `OF word.bit` instead of forcing `BOOL`, (c) enforcing trailing newlines/spacing between major sections.
- Attribute coverage: capture/display optional tag attributes (e.g., Comment, EngineeringUnit, Max/Min, State0/1) without exporting values.
- Search/filter UX: add a tree search box; per-branch select-all/none toggles for large projects.
- Validation preview: right-pane “export preview” of the emitted block (post-transform) for the selected item.
- Compatibility matrix: doc callouts for Studio 5000 vs. AVEVA Edge quirks (tabs-only indentation, AOI local tags).
- CLI entry point: headless import/filter/export using the same parser/models.
- Performance: profile on large files; consider tighter scanners for UDT/AOI blocks if needed; optional progress indicator for very large imports.
- Typing/tests: extend regex/unit coverage (UDT member variants with dims/whitespace; TAG termination); broaden sanity checks (duplicate UDT members, AOI params referencing missing locals).
