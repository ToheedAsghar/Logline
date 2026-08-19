import Foundation

public class ProcessManager {
    public static let shared = ProcessManager()
    
    private var syncProcess: Process?
    
    public var isRunning: Bool {
        return syncProcess?.isRunning ?? false
    }
    
    private init() {}
    
    public func startSyncAgent() throws {
        // Terminate any existing process first
        terminateSyncAgent()
        
        let token = try KeychainManager.getToken()
        guard let validToken = token, !validToken.isEmpty else {
            print("ProcessManager: No token found in Keychain, cannot start sync agent.")
            return
        }
        
        let process = Process()
        
        // For development, we assume we are running from the repo root
        // In production (Phase 4), this will point to Bundle.main.url(forResource: "tracker", withExtension: nil)
        let fileManager = FileManager.default
        let currentPath = fileManager.currentDirectoryPath
        process.executableURL = URL(fileURLWithPath: "\(currentPath)/tracker/.venv/bin/python")
        process.arguments = ["-m", "tracker.sync.agent"]
        
        // Setup standard input pipe to pass the token securely
        let pipe = Pipe()
        process.standardInput = pipe
        
        // Pipe stdout/stderr for debugging
        let outPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = outPipe
        
        outPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty, let str = String(data: data, encoding: .utf8) {
                print("[Python] \(str)", terminator: "")
            }
        }
        
        self.syncProcess = process
        
        do {
            try process.run()
            print("ProcessManager: Started python sync agent (PID: \(process.processIdentifier))")
            
            // Write token to stdin and close it so python can read to EOF
            if let data = validToken.data(using: .utf8) {
                pipe.fileHandleForWriting.write(data)
            }
            pipe.fileHandleForWriting.closeFile()
            
        } catch {
            print("ProcessManager: Failed to start process: \(error)")
            self.syncProcess = nil
            throw error
        }
    }
    
    public func terminateSyncAgent() {
        if let process = syncProcess, process.isRunning {
            process.terminate()
            process.waitUntilExit()
            print("ProcessManager: Terminated python sync agent.")
        }
        syncProcess = nil
    }
}
