import Foundation

public class ProcessManager {
    public static let shared = ProcessManager()
    
    private var trackerProcess: Process?
    private var syncProcess: Process?
    
    public var isRunning: Bool {
        return trackerProcess?.isRunning ?? false
    }
    
    // Notification to let the app know the process died unexpectedly
    public static let trackerDidCrashNotification = Notification.Name("trackerDidCrashNotification")
    
    private init() {}
    
    /// Starts the continuous tracker daemon (tracker.main)
    public func startTrackerDaemon() throws {
        terminateTrackerDaemon()
        
        let process = Process()
        let fileManager = FileManager.default
        let currentPath = fileManager.currentDirectoryPath
        process.executableURL = URL(fileURLWithPath: "\(currentPath)/tracker/.venv/bin/python")
        process.arguments = ["-m", "tracker.main"]
        
        // Pipe stdout/stderr for debugging
        let outPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = outPipe
        
        outPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty, let str = String(data: data, encoding: .utf8) {
                print("[Tracker] \(str)", terminator: "")
            }
        }
        
        process.terminationHandler = { [weak self] p in
            guard let self = self else { return }
            // If the process wasn't intentionally terminated by us (where we set trackerProcess to nil)
            if self.trackerProcess === p {
                self.trackerProcess = nil
                DispatchQueue.main.async {
                    NotificationCenter.default.post(name: ProcessManager.trackerDidCrashNotification, object: nil)
                }
            }
        }
        
        self.trackerProcess = process
        
        do {
            try process.run()
            print("ProcessManager: Started tracker daemon (PID: \(process.processIdentifier))")
        } catch {
            print("ProcessManager: Failed to start tracker: \(error)")
            self.trackerProcess = nil
            throw error
        }
    }
    
    /// Terminates the continuous tracker daemon
    public func terminateTrackerDaemon() {
        if let process = trackerProcess, process.isRunning {
            let p = process
            trackerProcess = nil // Clear it first so terminationHandler knows it was intentional
            p.terminate()
            p.waitUntilExit()
            print("ProcessManager: Terminated tracker daemon.")
        } else {
            trackerProcess = nil
        }
    }
    
    /// Brutally terminates any running process for graceful app shutdown
    public func terminateAll() {
        terminateTrackerDaemon()
        if let process = syncProcess, process.isRunning {
            process.terminate()
            process.waitUntilExit()
            print("ProcessManager: Terminated active sync agent.")
        }
        syncProcess = nil
    }
    
    /// Runs a one-shot sync agent upload
    public func triggerSync() async throws {
        guard syncProcess == nil else {
            print("ProcessManager: Sync agent already running, skipping.")
            return
        }
        
        let token = try KeychainManager.getToken()
        guard let validToken = token, !validToken.isEmpty else {
            print("ProcessManager: No token found in Keychain, cannot run sync agent.")
            return
        }
        
        let process = Process()
        self.syncProcess = process
        
        let fileManager = FileManager.default
        let currentPath = fileManager.currentDirectoryPath
        process.executableURL = URL(fileURLWithPath: "\(currentPath)/tracker/.venv/bin/python")
        process.arguments = ["-m", "tracker.sync.agent"]
        
        let pipe = Pipe()
        process.standardInput = pipe
        
        let outPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = outPipe
        
        outPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty, let str = String(data: data, encoding: .utf8) {
                print("[SyncAgent] \(str)", terminator: "")
            }
        }
        
        try process.run()
        print("ProcessManager: Started one-shot sync agent (PID: \(process.processIdentifier))")
        
        if let data = validToken.data(using: .utf8) {
            pipe.fileHandleForWriting.write(data)
        }
        pipe.fileHandleForWriting.closeFile()
        
        // Wait for the sync agent to finish asynchronously
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            process.terminationHandler = { [weak self] _ in
                print("ProcessManager: Sync agent finished.")
                self?.syncProcess = nil
                continuation.resume()
            }
        }
    }
}
