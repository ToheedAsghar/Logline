import Cocoa
import Foundation

class AppDelegate: NSObject, NSApplicationDelegate {
    var pythonProcess: Process?

    func applicationDidFinishLaunching(_ aNotification: Notification) {
        runPythonChild()
    }
    
    func runPythonChild() {
        let pythonPath = "/Users/toheed.asghar/Documents/projects/logline/.worktrees/tracker-desktop-app/tracker/test_env/bin/python"
        let scriptPath = "-m"
        let modulePath = "tracker.ax_probe"
        
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [scriptPath, modulePath]
        // Run it in the directory where 'tracker' is a module
        process.currentDirectoryURL = URL(fileURLWithPath: "/Users/toheed.asghar/Documents/projects/logline/.worktrees/tracker-desktop-app")
        
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        
        do {
            try process.run()
            pythonProcess = process
            
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            if let output = String(data: data, encoding: .utf8) {
                try? output.write(toFile: "/tmp/spike.log", atomically: true, encoding: .utf8)
            }
        } catch {
            try? "Failed: \(error)".write(toFile: "/tmp/spike.log", atomically: true, encoding: .utf8)
        }
    }
    
    func applicationWillTerminate(_ aNotification: Notification) {
        pythonProcess?.terminate()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
