import Foundation
import SQLite3

public struct TrackerEvent: Identifiable {
    public let id: String
    public let appName: String
    public let windowTitle: String?
    public let startedAt: String
    public let endedAt: String
    public let isIdle: Bool
}

public class DatabaseReader {
    private let dbPath: String
    
    public init() {
        let fileManager = FileManager.default
        if let appSupport = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            self.dbPath = appSupport.appendingPathComponent("Logline/tracker.db").path
        } else {
            self.dbPath = ""
        }
    }
    
    public func fetchRecentEvents(limit: Int = 500) -> [TrackerEvent] {
        guard !dbPath.isEmpty, FileManager.default.fileExists(atPath: dbPath) else {
            return []
        }
        
        var db: OpaquePointer?
        if sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) != SQLITE_OK {
            return []
        }
        defer { sqlite3_close(db) }
        
        let query = "SELECT id, app_name, window_title, started_at, ended_at, is_idle FROM sessions ORDER BY ended_at DESC LIMIT ?"
        var statement: OpaquePointer?
        
        if sqlite3_prepare_v2(db, query, -1, &statement, nil) != SQLITE_OK {
            return []
        }
        defer { sqlite3_finalize(statement) }
        
        sqlite3_bind_int(statement, 1, Int32(limit))
        
        var events: [TrackerEvent] = []
        
        while sqlite3_step(statement) == SQLITE_ROW {
            let id = String(cString: sqlite3_column_text(statement, 0))
            let appName = String(cString: sqlite3_column_text(statement, 1))
            
            var windowTitle: String? = nil
            if let titlePtr = sqlite3_column_text(statement, 2) {
                windowTitle = String(cString: titlePtr)
            }
            
            let startedAt = String(cString: sqlite3_column_text(statement, 3))
            let endedAt = String(cString: sqlite3_column_text(statement, 4))
            let isIdle = sqlite3_column_int(statement, 5) != 0
            
            events.append(TrackerEvent(
                id: id,
                appName: appName,
                windowTitle: windowTitle,
                startedAt: startedAt,
                endedAt: endedAt,
                isIdle: isIdle
            ))
        }
        
        return events
    }
}
