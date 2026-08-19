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
        case quitAdjacent
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
    
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        // Crucial: do not terminate when the window closes
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
        
        menu.addItem(NSMenuItem.separator())
        
        let errorItem = NSMenuItem(title: "Simulate Error State", action: #selector(simulateError), keyEquivalent: "")
        menu.addItem(errorItem)
        
        menu.addItem(NSMenuItem.separator())
        
        let quitItem = NSMenuItem(title: "Quit", action: #selector(quitApp), keyEquivalent: "q")
        menu.addItem(quitItem)
        
        statusItem.menu = menu
    }
    
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
        mainWindow.isReleasedWhenClosed = false // Keep memory so it can be reopened
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
        case .quitAdjacent:
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
        currentState = .quitAdjacent
        updateIcon()
    }
    
    @objc func quitApp() {
        NSApplication.shared.terminate(nil)
    }
}
