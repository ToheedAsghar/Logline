import SwiftUI
import AppKit
import ServiceManagement

@main
struct TrackerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        // We use an empty Settings scene to satisfy the App requirement,
        // but we manage our own NSWindow in the AppDelegate to ensure
        // it hides instead of closing, which fits menubar app semantics perfectly.
        Settings {
            EmptyView()
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var mainWindow: NSWindow!
    
    enum AgentState {
        case running
        case paused
        case error
    }
    var currentState: AgentState = .running

    func applicationDidFinishLaunching(_ notification: Notification) {
        KeychainManager.migrateLegacyToken()
        print("LoglineTracker App Launched")
        
        let availableFamilies = NSFontManager.shared.availableFontFamilies
        if availableFamilies.contains("Space Grotesk") {
            print("Font Check: Space Grotesk FOUND")
        } else {
            print("Font Check: Space Grotesk MISSING")
        }
        if availableFamilies.contains("JetBrains Mono") {
            print("Font Check: JetBrains Mono FOUND")
        } else {
            print("Font Check: JetBrains Mono MISSING")
        }
        
        setupMenu()
        setupWindow()
        updateIcon()
        
        do {
            try SMAppService.mainApp.register()
            print("Successfully registered for login auto-launch.")
        } catch {
            print("Failed to register for login auto-launch: \(error)")
        }
        
        mainWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        
        // Start the tracker if we launch in the running state
        if currentState == .running {
            do {
                try ProcessManager.shared.startTrackerDaemon()
            } catch {
                print("Failed to start tracker: \(error)")
                self.currentState = .error
                self.updateIcon()
            }
        }
        
        NotificationCenter.default.addObserver(forName: Notification.Name("syncPollDidFail"), object: nil, queue: .main) { [weak self] _ in
            self?.currentState = .error
            self?.updateIcon()
        }
        
        NotificationCenter.default.addObserver(forName: Notification.Name("syncPollDidSucceed"), object: nil, queue: .main) { [weak self] _ in
            guard let self = self else { return }
            if self.currentState == .error {
                self.currentState = ProcessManager.shared.isRunning ? .running : .paused
                self.updateIcon()
            }
        }
        
        NotificationCenter.default.addObserver(forName: ProcessManager.trackerDidCrashNotification, object: nil, queue: .main) { [weak self] _ in
            self?.currentState = .error
            self?.updateIcon()
        }
    }
    
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
        ProcessManager.shared.terminateAll()
    }
    
    private func setupMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        
        let menu = NSMenu()
        
        let showItem = NSMenuItem(title: "Show Logline Tracker", action: #selector(showWindow), keyEquivalent: "")
        menu.addItem(showItem)
        menu.addItem(NSMenuItem.separator())
        
        let startItem = NSMenuItem(title: "Start Tracker", action: #selector(startTracker), keyEquivalent: "")
        menu.addItem(startItem)
        
        let stopItem = NSMenuItem(title: "Stop Tracker", action: #selector(stopTracker), keyEquivalent: "")
        menu.addItem(stopItem)
        
        #if DEBUG
        menu.addItem(NSMenuItem.separator())
        let errorItem = NSMenuItem(title: "Simulate Error State", action: #selector(simulateError), keyEquivalent: "")
        menu.addItem(errorItem)
        #endif
        
        menu.addItem(NSMenuItem.separator())
        
        let quitItem = NSMenuItem(title: "Quit", action: #selector(quitApp), keyEquivalent: "q")
        menu.addItem(quitItem)
        
        statusItem.menu = menu
    }
    
    /// Sets up the main window instance and configures its default behavior.
    /// The window's `isReleasedWhenClosed` property must be false to prevent it from
    /// being deallocated entirely when the user clicks the red close button, allowing
    /// the application to efficiently reopen the same window object later.
    private func setupWindow() {
        let contentView = MainView()
        
        mainWindow = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 450, height: 550),
            styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        
        mainWindow.center()
        mainWindow.setFrameAutosaveName("Main Window")
        mainWindow.title = "Logline Tracker"
        mainWindow.contentView = NSHostingView(rootView: contentView)
        mainWindow.isReleasedWhenClosed = false
    }
    
    private func updateIcon() {
        guard let button = statusItem.button else { return }
        
        var symbolName = "circle.fill"
        var color = NSColor.systemGreen
        
        switch currentState {
        case .running:
            symbolName = "arrow.triangle.2.circlepath.circle.fill"
            color = NSColor.systemGreen
        case .paused:
            symbolName = "pause.circle.fill"
            color = NSColor.systemOrange
        case .error:
            symbolName = "exclamationmark.triangle.fill"
            color = NSColor.systemRed
        }
        
        let config = NSImage.SymbolConfiguration(pointSize: 15, weight: .regular)
            .applying(.init(hierarchicalColor: color))
        
        if let image = NSImage(systemSymbolName: symbolName, accessibilityDescription: nil) {
            button.image = image.withSymbolConfiguration(config)
        } else {
            button.title = "Logline"
        }
    }
    
    @objc func showWindow() {
        mainWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    
    @objc func startTracker() {
        currentState = .running
        updateIcon()
        do {
            try ProcessManager.shared.startTrackerDaemon()
        } catch {
            print("Failed to start tracker: \(error)")
            currentState = .error
            updateIcon()
        }
    }
    
    @objc func stopTracker() {
        currentState = .paused
        updateIcon()
        ProcessManager.shared.terminateTrackerDaemon()
    }
    
    @objc func simulateError() {
        currentState = .error
        updateIcon()
    }
    
    @objc func quitApp() {
        NSApplication.shared.terminate(nil)
    }
}
