import SwiftUI

@main
struct TrackerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        KeychainManager.migrateLegacyToken()
        print("LoglineTracker App Launched")
        
        do {
            try ProcessManager.shared.startSyncAgent()
        } catch {
            print("Failed to start agent: \(error)")
        }
    }
    
    func applicationWillTerminate(_ notification: Notification) {
        ProcessManager.shared.terminateSyncAgent()
    }
}
