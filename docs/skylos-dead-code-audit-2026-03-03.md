## Skylos Dead Code Audit (2026-03-03)

Confident removals from the March 3, 2026 Skylos pass:

- `debug_utils.py`: removed. No Python source or tests imported this module, and the only non-code reference that affected runtime behavior was `transfer_config.json`, which was updated in the same change. The file contained orphaned instrumentation helpers with no CLI entry point, plugin hook, or reflective lookup.
- `NotificationManager.clear_all_toasts()`: removed from `notification_manager.py`. A repo-wide Python search found only the defining line, so it was not used directly, as a callback, or from tests.
- `HeadlessMode.require_display()`: removed from `headless_mode.py`. A repo-wide Python search found only the defining line, so it was not used as a decorator or direct call site.
- `HeadlessMode.is_display_available()`: removed from `headless_mode.py` after the first cleanup pass made it definition-only. It had no remaining callers in Python sources or tests.
- Unused imports removed from `controllers/filter_coordinator.py`, `controllers/settings_controller.py`, and `controllers/shot_selection_controller.py`. These names were only present in comments or string-based `cast(...)` calls, so removing them does not change runtime behavior.

Items intentionally kept after review:

- Qt lifecycle hooks, signals, and similar framework-managed members remain because static analysis undercounts reflective access and signal-slot wiring.
- `thumbnail_finders.Config` remains despite Skylos flagging it as unused; the existing inline note documents that tests monkeypatch it intentionally.
- `main_window.BaseShotModel` remains despite Skylos flagging it as unused; the file already documents it as a deliberate type-only aid for string-based `cast(...)` usage.
- Public helper methods on core UI/controllers with no in-repo callers were left in place when they looked like external or future API surface rather than clearly abandoned code.
