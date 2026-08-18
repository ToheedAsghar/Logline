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

run-negative:
	@echo "Running negative control (launchctl submit) to exclude Terminal ancestry..."
	rm -f /tmp/spike.log
	# Use a unique label for the launchctl job
	launchctl submit -l com.logline.spike.negative -- $(PWD)/$(EXECUTABLE)
	@echo "Waiting for background process to finish..."
	@sleep 3
	launchctl remove com.logline.spike.negative
	@cat /tmp/spike.log || echo "No log found."
