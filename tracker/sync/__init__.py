"""Uploads recorded sessions to the Logline backend.

Deliberately separate from the capture daemon, which must keep running through a backend outage. The two share
only the SQLite file, which sync opens read-only.
"""
