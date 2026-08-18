## Task 1: Add keychain storage for the token

**Description:** Implement `secure_storage.py` and update requirements to use `keyring` for macOS Keychain storage, replacing manual token files.

**Acceptance criteria:**
- [ ] `keyring` added to `requirements.txt`.
- [ ] `secure_storage.py` created with `store_token()` and `get_token()`.
- [ ] Manual test verifies token goes to Keychain.

**Verification:**
- [ ] Tests pass: `make test`
- [ ] Build succeeds: N/A
- [ ] Manual check: Run `python -c "from secure_storage import *; store_token('test')"` and verify in Keychain Access.

**Dependencies:** None

**Files likely touched:**
- `requirements.txt`
- `tracker/storage/secure_storage.py` (New)

**Estimated scope:** Small: 1-2 files

---

## Task 2: Create Main UI Layout

**Description:** Scaffold the main desktop window layout containing Enrollment form, Sync Status label, and Events View list.

**Acceptance criteria:**
- [ ] Main window appears when launched.
- [ ] Has an input field for the token and a Submit button.
- [ ] Has a label showing "Not Connected".
- [ ] Has a list/treeview for events.

**Verification:**
- [ ] Tests pass: N/A
- [ ] Build succeeds: Window launches without errors.
- [ ] Manual check: Run `python ui/app.py` and see the layout.

**Dependencies:** Task 1

**Files likely touched:**
- `tracker/ui/app.py` (New)
- `tracker/ui/components.py` (New)

**Estimated scope:** Medium: 3-5 files

---

## Task 3: Implement Enrollment Logic

**Description:** Wire the Submit button to validate the token against `GET /tracker/sync/status` and store it in the Keychain.

**Acceptance criteria:**
- [ ] Validation call made to the backend.
- [ ] Upon success, token stored via `secure_storage.py`.
- [ ] UI status updates to "Connected".

**Verification:**
- [ ] Tests pass: Unit tests mock backend/keyring and verify success/failure flows.
- [ ] Build succeeds: N/A
- [ ] Manual check: Submit valid/invalid tokens and verify UI changes.

**Dependencies:** Task 2

**Files likely touched:**
- `tracker/ui/app.py`

**Estimated scope:** Small: 1-2 files

---

## Task 4: Implement Sync Status Polling

**Description:** Poll `GET /tracker/sync/status` periodically and update the UI status label.

**Acceptance criteria:**
- [ ] Polling loop runs in the background.
- [ ] Label updates to Synced/Syncing/Stale based on the response.

**Verification:**
- [ ] Tests pass: Unit tests verify status label parsing.
- [ ] Build succeeds: N/A
- [ ] Manual check: Run app, see status update over time.

**Dependencies:** Task 3

**Files likely touched:**
- `tracker/ui/app.py`

**Estimated scope:** Small: 1-2 files

---

## Task 5: Implement Live Events View

**Description:** Read the last 500 rows from `tracker.db` in read-only mode and populate the UI list.

**Acceptance criteria:**
- [ ] Connects to SQLite `tracker.db` in `mode=ro`.
- [ ] Fetches latest 500 events and renders them in the list.
- [ ] Auto-refreshes periodically or on trigger.

**Verification:**
- [ ] Tests pass: Verify SQL query executes correctly.
- [ ] Build succeeds: N/A
- [ ] Manual check: Generate local events (using logline headless) and see them appear in UI.

**Dependencies:** Task 4

**Files likely touched:**
- `tracker/ui/app.py`
- `tracker/storage/db.py` (Existing, to be modified/accessed)

**Estimated scope:** Medium: 3-5 files

---

## Task 6: Integrate with Headless Tracker Loop

**Description:** Integrate the existing Logline tracker loop into the app, so it tracks background activity while the UI is open.

**Acceptance criteria:**
- [ ] UI loop and tracker loop run concurrently.
- [ ] Tracker uses the token from `secure_storage.py`.

**Verification:**
- [ ] Tests pass: Integration tests if possible.
- [ ] Build succeeds: N/A
- [ ] Manual check: App opens, tracks events locally, syncs them to backend, and shows in UI.

**Dependencies:** Task 5

**Files likely touched:**
- `tracker/main.py`
- `tracker/ui/app.py`

**Estimated scope:** Medium: 3-5 files

---

## Task 7: py2app Packaging

**Description:** Set up `setup.py` using `py2app` to bundle the app into a macOS `.app`.

**Acceptance criteria:**
- [ ] `setup.py` exists with py2app configuration.
- [ ] Running `python setup.py py2app` generates a working `.app`.

**Verification:**
- [ ] Tests pass: N/A
- [ ] Build succeeds: `python setup.py py2app` works.
- [ ] Manual check: Double-click the built `.app` and verify it launches.

**Dependencies:** Task 6

**Files likely touched:**
- `tracker/setup.py` (New)
- `tracker/packaging/build_app.sh` (New)

**Estimated scope:** Small: 1-2 files
