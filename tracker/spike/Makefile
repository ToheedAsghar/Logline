.PHONY: clean build run-positive run-negative

APP_NAME = Spike.app
MACOS_DIR = $(APP_NAME)/Contents/MacOS
EXECUTABLE = $(MACOS_DIR)/SpikeApp

clean:
	rm -f /tmp/spike.log
	rm -rf $(APP_NAME)

build: clean
	mkdir -p $(MACOS_DIR)
	# Add a minimal Info.plist so codesign recognizes the bundle format
	cp ../../tracker-app/Info.plist $(APP_NAME)/Contents/Info.plist
	# Note: Uses a local self-signed certificate to ensure a stable designated requirement
	# across rebuilds for accurate TCC persistence testing.
	swiftc main.swift -o $(EXECUTABLE)
	codesign -s BD94A6C648F35634FFC1294C30B3A51E386B27B4 --force $(APP_NAME)

run-positive:
	@echo "Running positive control (open-launched) to exclude Terminal ancestry..."
	rm -f /tmp/spike.log
	open $(APP_NAME)
	@echo "Waiting for background process to finish..."
	@sleep 3
	@cat /tmp/spike.log || echo "No log found."

run-headless:
	@echo "Running headless positive control (launchctl submit on SpikeApp) to prove detached grant..."
	rm -f /tmp/spike.log
	launchctl submit -l com.logline.spike.headless -- $(PWD)/$(EXECUTABLE)
	@echo "Waiting for background process to finish..."
	@sleep 3
	launchctl remove com.logline.spike.headless
	@cat /tmp/spike.log || echo "No log found."

run-negative:
	@echo "Running true cross-identity negative control (launchctl submit on bare python)..."
	rm -f /tmp/true_negative.log
	launchctl submit -l com.logline.spike.negative -- /Users/toheed.asghar/Documents/projects/logline/.worktrees/tracker-desktop-app/tracker/test_env/bin/python -c "import sys; sys.path.append('/Users/toheed.asghar/Documents/projects/logline/.worktrees/tracker-desktop-app'); import json, tracker.ax_probe; open('/tmp/true_negative.log', 'w').write(json.dumps(tracker.ax_probe.probe()) + '\n')"
	@echo "Waiting for background process to finish..."
	@sleep 3
	launchctl remove com.logline.spike.negative
	@cat /tmp/true_negative.log || echo "No log found."
