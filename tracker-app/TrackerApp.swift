import SwiftUI
import AppKit

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
        
        setupMenu()
        setupWindow()
        updateIcon()
        
        mainWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        
        do {
            try ProcessManager.shared.startSyncAgent()
        } catch {
            print("Failed to start agent: \(error)")
        }
    }
    
    /// The application must not terminate when its only visible window is closed.
    /// Returning false here ensures the app stays alive as a background menu-bar app
    /// and the window can be reopened later from the status item menu.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
        ProcessManager.shared.terminateSyncAgent()
    }
    
    private func setupMenu() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        
        let menu = NSMenu()
        
        let showItem = NSMenuItem(title: "Show Logline Tracker", action: #selector(showWindow), keyEquivalent: "")
        menu.addItem(showItem)
        menu.addItem(NSMenuItem.separator())
        
        let startItem = NSMenuItem(title: "Start Sync", action: #selector(startSync), keyEquivalent: "")
        menu.addItem(startItem)
        
        let stopItem = NSMenuItem(title: "Stop Sync", action: #selector(stopSync), keyEquivalent: "")
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
    
    @objc func startSync() {
        currentState = .running
        updateIcon()
    }
    
    @objc func stopSync() {
        currentState = .paused
        updateIcon()
    }
    
    @objc func simulateError() {
        currentState = .error
        updateIcon()
    }
    
    @objc func quitApp() {
        NSApplication.shared.terminate(nil)
    }
}
