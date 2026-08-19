import Foundation

public enum Constants {
    public enum API {
        public static let defaultBaseURL = "http://localhost:8000"
        public static let syncConfigPath = "Logline/sync.json"
        public static let checkpointPath = "/tracker/sync/checkpoint"
    }
    
    public enum ErrorMessages {
        public static let emptyToken = "Token cannot be empty."
        public static let invalidURL = "Invalid base URL configured."
        public static let invalidResponse = "Invalid response from server."
        public static let invalidJSON = "Invalid JSON response from server."
        public static let connectionFailedPrefix = "Connection failed: "
        public static let networkErrorPrefix = "Network error: "
    }
}
