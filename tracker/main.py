"""Entry point / run loop for the local activity tracker. Wiring only — no business logic."""

from pathlib import Path

from PyObjCTools import AppHelper

from tracker import console
from tracker.session.manager import SessionManager
from tracker.storage import db
from tracker.watchers.app_watcher import AppWatcher
from tracker.watchers.idle_watcher import IdleWatcher
from tracker.watchers.sleep_watcher import SleepWatcher
from tracker.watchers.title_watcher import TitleWatcher


def main():
    conn = db.get_connection()
    manager = SessionManager(conn)

    def on_app_activated(bundle_id, app_name):
        print(console.event("switch", f"{app_name} ({bundle_id})"))
        idle_watcher.mark_active()
        title_watcher.reset()
        manager.on_app_activated(bundle_id, app_name)

    def on_title_changed(bundle_id, app_name, window_title, context=None):
        detail = dict(getattr(context, "detail", None) or {})
        project = getattr(context, "project_path", None)
        if project:
            detail = {"project": Path(project).name, **detail}
        headline = f"{app_name} {console.truncate(window_title or '')!r}"
        print(console.event("title", headline, detail=detail))
        idle_watcher.resync()
        manager.on_title_changed(bundle_id, app_name, window_title, context=context)

    def on_idle_start(stopped_at):
        print(console.event("idle_start", f"input stopped at {stopped_at.strftime('%H:%M:%S')}"))
        manager.on_idle_start(stopped_at)

    def on_idle_end():
        print(console.event("idle_end", "input resumed"))
        manager.on_idle_end()

    def on_sleep():
        print(console.event("sleep", "system going to sleep"))
        manager.on_sleep()

    def on_wake():
        print(console.event("wake", "system woke up"))

    def on_lock():
        print(console.event("lock", "screen locked"))
        manager.on_lock()

    def on_unlock():
        print(console.event("unlock", "screen unlocked"))

    app_watcher = AppWatcher(callback=on_app_activated)
    title_watcher = TitleWatcher(callback=on_title_changed)
    idle_watcher = IdleWatcher(on_idle_start=on_idle_start, on_idle_end=on_idle_end)
    sleep_watcher = SleepWatcher(on_sleep=on_sleep, on_wake=on_wake, on_lock=on_lock, on_unlock=on_unlock)

    app_watcher.start()
    title_watcher.start()
    idle_watcher.start()
    sleep_watcher.start()
    manager.start_heartbeat()

    print("tracker running — watching for app switches. Ctrl+C to stop.")
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop_heartbeat()
        sleep_watcher.stop()
        idle_watcher.stop()
        title_watcher.stop()
        app_watcher.stop()
        conn.close()


if __name__ == "__main__":
    main()
