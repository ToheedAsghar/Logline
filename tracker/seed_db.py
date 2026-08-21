import sqlite3
import os
from datetime import datetime, timezone, timedelta

db_path = os.path.expanduser("~/Library/Application Support/Logline/tracker.db")
os.makedirs(os.path.dirname(db_path), exist_ok=True)
conn = sqlite3.connect(db_path)
c = conn.cursor()

base = datetime.now(timezone.utc)
c.execute("DELETE FROM sessions")
for i in range(5):
    start = base - timedelta(minutes=10 - i)
    end = start + timedelta(minutes=1)
    c.execute('''
        INSERT INTO sessions (id, app_name, bundle_id, window_title, started_at, ended_at, end_reason, is_idle)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (f"test_{i}", "Xcode", "com.apple.dt.Xcode", "Logline.xcodeproj", start.isoformat(), end.isoformat(), "app_switch", i % 2))

conn.commit()
conn.close()
print(f"Seeded {db_path} with test events")
