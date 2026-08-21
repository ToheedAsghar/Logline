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
    
    private func getPythonProcessArgs(isSync: Bool) -> (URL, [String]) {
        if let bundledURL = Bundle.main.url(forResource: "logline_tracker", withExtension: nil) {
            let args = isSync ? ["sync"] : []
            return (bundledURL, args)
        }
        
        let fileManager = FileManager.default
        let currentPath = fileManager.currentDirectoryPath
        let executableURL = URL(fileURLWithPath: "\(currentPath)/tracker/.venv/bin/python")
        let args = isSync ? ["-m", "tracker.sync.agent"] : ["-m", "tracker.main"]
        return (executableURL, args)
    }
    
    /// Starts the continuous tracker daemon (tracker.main)
    public func startTrackerDaemon() throws {
        terminateTrackerDaemon()
        
        let process = Process()
        let (executableURL, args) = getPythonProcessArgs(isSync: false)
        process.executableURL = executableURL
        process.arguments = args
        
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
            
            let timeout = Date().addingTimeInterval(3.0)
            while p.isRunning && Date() < timeout {
                Thread.sleep(forTimeInterval: 0.1)
            }
            
            if p.isRunning {
                NSLog("ProcessManager: Tracker daemon did not exit gracefully within timeout, force-killing...")
                kill(p.processIdentifier, SIGKILL)
                p.waitUntilExit()
            } else {
                NSLog("ProcessManager: Terminated tracker daemon gracefully.")
            }
        } else {
            trackerProcess = nil
        }
    }
    
    /// Brutally terminates any running process for graceful app shutdown
    public func terminateAll() {
        terminateTrackerDaemon()
        if let process = syncProcess, process.isRunning {
            process.terminate()
            let timeout = Date().addingTimeInterval(3.0)
            while process.isRunning && Date() < timeout {
                Thread.sleep(forTimeInterval: 0.1)
            }
            if process.isRunning {
                NSLog("ProcessManager: Sync agent did not exit gracefully within timeout, force-killing...")
                kill(process.processIdentifier, SIGKILL)
                process.waitUntilExit()
            } else {
                NSLog("ProcessManager: Terminated active sync agent gracefully.")
            }
        }
        syncProcess = nil
    }
    
    /// Runs a one-shot sync agent upload
    public func triggerSync() async throws {
        guard syncProcess == nil else {
            NSLog("ProcessManager: Sync agent is already running, skipping trigger.")
            return
        }
        
        let token = try? KeychainManager.getToken()
        guard let validToken = token, !validToken.isEmpty else {
            NSLog("ProcessManager: No token found in Keychain, cannot run sync agent.")
            return
        }
        
        let process = Process()
        let (executableURL, args) = getPythonProcessArgs(isSync: true)
        process.executableURL = executableURL
        process.arguments = args
        let currentPath = FileManager.default.currentDirectoryPath
        process.currentDirectoryURL = URL(fileURLWithPath: currentPath)
        
        let pipe = Pipe()
        process.standardInput = pipe
        
        process.terminationHandler = { [weak self] p in
            DispatchQueue.main.async {
                NSLog("ProcessManager: Sync agent (PID: \(p.processIdentifier)) finished with status \(p.terminationStatus).")
                if self?.syncProcess === p {
                    self?.syncProcess = nil
                }
            }
        }
        
        do {
            try process.run()
            self.syncProcess = process
            NSLog("ProcessManager: Started one-shot sync agent (PID: \(process.processIdentifier))")
            
            if let data = validToken.data(using: .utf8) {
                pipe.fileHandleForWriting.write(data)
            }
            try pipe.fileHandleForWriting.close()
        } catch {
            NSLog("ProcessManager: Failed to start sync agent: \(error)")
            throw error
        }
    }
}
