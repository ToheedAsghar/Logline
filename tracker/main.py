"""Entry point / run loop for the local activity tracker. Wiring only — no business logic."""

import signal
import sys
from pathlib import Path

from PyObjCTools import AppHelper

from tracker import console
from tracker.constants import (
    EVENT_KIND_IDLE_END, EVENT_KIND_IDLE_START, EVENT_KIND_LOCK, EVENT_KIND_SLEEP, EVENT_KIND_SWITCH, EVENT_KIND_TITLE,
    EVENT_KIND_UNLOCK, EVENT_KIND_WAKE, EXIT_ALREADY_RUNNING, REFUSING_TO_START_MSG, TRACKER_RUNNING_MSG,
)
from tracker.context import resolver_capability_summary
from tracker.session.manager import SessionManager
from tracker.singleton import AlreadyRunning, SingleInstanceLock
from tracker.storage import db
from tracker.watchers.app_watcher import AppWatcher
from tracker.watchers.idle_watcher import IdleWatcher
from tracker.watchers.sleep_watcher import SleepWatcher
from tracker.watchers.title_watcher import TitleWatcher


def main():
    lock = SingleInstanceLock()
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        print(REFUSING_TO_START_MSG % exc, file=sys.stderr)
        return EXIT_ALREADY_RUNNING

    try:
        return _run()
    finally:
        lock.release()


def _run():
    print(resolver_capability_summary())
    conn = db.get_connection()
    manager = SessionManager(conn)

    def on_app_activated(bundle_id, app_name):
        print(console.event(EVENT_KIND_SWITCH, f"{app_name} ({bundle_id})"))
        idle_watcher.mark_active()
        title_watcher.reset()
        manager.on_app_activated(bundle_id, app_name)

    def on_title_changed(bundle_id, app_name, window_title, context=None):
        detail = dict(getattr(context, "detail", None) or {})
        project = getattr(context, "project_path", None)
        if project:
            detail = {"project": Path(project).name, **detail}
        headline = f"{app_name} {console.truncate(window_title or '')!r}"
        print(console.event(EVENT_KIND_TITLE, headline, detail=detail))
        idle_watcher.resync()
        manager.on_title_changed(bundle_id, app_name, window_title, context=context)

    def on_idle_start(stopped_at):
        print(console.event(EVENT_KIND_IDLE_START, f"input stopped at {stopped_at.strftime('%H:%M:%S')}"))
        manager.on_idle_start(stopped_at)

    def on_idle_end():
        print(console.event(EVENT_KIND_IDLE_END, "input resumed"))
        manager.on_idle_end()

    def on_sleep():
        print(console.event(EVENT_KIND_SLEEP, "system going to sleep"))
        manager.on_sleep()

    def on_wake():
        print(console.event(EVENT_KIND_WAKE, "system woke up"))

    def on_lock():
        print(console.event(EVENT_KIND_LOCK, "screen locked"))
        manager.on_lock()

    def on_unlock():
        print(console.event(EVENT_KIND_UNLOCK, "screen unlocked"))

    app_watcher = AppWatcher(callback=on_app_activated)
    title_watcher = TitleWatcher(callback=on_title_changed)
    idle_watcher = IdleWatcher(on_idle_start=on_idle_start, on_idle_end=on_idle_end)
    sleep_watcher = SleepWatcher(on_sleep=on_sleep, on_wake=on_wake, on_lock=on_lock, on_unlock=on_unlock)

    app_watcher.start()
    title_watcher.start()
    idle_watcher.start()
    sleep_watcher.start()
    manager.start_heartbeat()

    # launchd stops an agent with SIGTERM, whose default action kills the process outright
    # and strands the open session for the next start to seal. Stopping the run loop instead
    # lets the shutdown path in the `finally` below run.
    signal.signal(signal.SIGTERM, lambda *_: AppHelper.stopEventLoop())

    print(TRACKER_RUNNING_MSG)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
