import Foundation

@MainActor
class EnrollmentViewModel: ObservableObject {
    @Published var isConnected: Bool = false
    @Published var deviceId: String? = nil
    @Published var lastSyncedAt: Date? = nil
    @Published var errorMessage: String? = nil
    @Published var isConnecting: Bool = false
    @Published var isDisconnecting: Bool = false
    
    private var pollTimer: Timer?
    
    func checkExistingEnrollment() {
        if let _ = try? KeychainManager.getToken(),
           let savedDeviceId = UserDefaults.standard.string(forKey: Constants.Storage.deviceIdKey) {
            isConnected = true
            deviceId = savedDeviceId
            errorMessage = nil
            startPolling()
        }
    }
    
    func connect(token: String) async {
        guard !token.isEmpty else {
            self.errorMessage = Constants.ErrorMessages.emptyToken
            return
        }
        
        self.isConnecting = true
        self.errorMessage = nil
        
        // Find base_url from sync.json or default
        var baseURL = Constants.API.defaultBaseURL
        let fileManager = FileManager.default
        if let appSupport = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            let syncConfigPath = appSupport.appendingPathComponent(Constants.API.syncConfigPath)
            if let data = try? Data(contentsOf: syncConfigPath),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let configURL = json["base_url"] as? String {
                baseURL = configURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            }
        }
        
        guard let url = URL(string: "\(baseURL)\(Constants.API.checkpointPath)") else {
            self.errorMessage = Constants.ErrorMessages.invalidURL
            self.isConnecting = false
            return
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else {
                self.errorMessage = Constants.ErrorMessages.invalidResponse
                self.isConnecting = false
                return
            }
            
            if httpResponse.statusCode == 200 {
                // Parse device ID
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let devId = json["device_id"] as? String {
                    self.deviceId = devId
                    
                    // Success: store token and persist device ID
                    try KeychainManager.storeToken(token)
                    UserDefaults.standard.set(devId, forKey: Constants.Storage.deviceIdKey)
                    
                    self.isConnected = true
                    self.errorMessage = nil
                    self.startPolling()
                } else {
                    self.errorMessage = Constants.ErrorMessages.invalidJSON
                }
            } else {
                // Extract error detail if available
                var detail = "HTTP \(httpResponse.statusCode)"
                if let errorJson = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let message = errorJson["detail"] as? String {
                    detail = message
                } else if let rawString = String(data: data, encoding: .utf8), !rawString.isEmpty {
                    detail = String(rawString.prefix(100))
                }
                self.errorMessage = "\(Constants.ErrorMessages.connectionFailedPrefix)\(detail)"
            }
        } catch {
            self.errorMessage = "\(Constants.ErrorMessages.networkErrorPrefix)\(error.localizedDescription)"
        }
        
        self.isConnecting = false
    }
    
    func disconnect() async {
        self.isDisconnecting = true
        self.stopPolling()
        
        let fileManager = FileManager.default
        var baseURL = Constants.API.defaultBaseURL
        if let appSupport = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            let syncConfigPath = appSupport.appendingPathComponent(Constants.API.syncConfigPath)
            if let data = try? Data(contentsOf: syncConfigPath),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let configURL = json["base_url"] as? String {
                baseURL = configURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            }
        }
        
        if let token = try? KeychainManager.getToken(), let devId = self.deviceId {
            if let url = URL(string: "\(baseURL)\(Constants.API.devicesPath)\(devId)") {
                var request = URLRequest(url: url)
                request.httpMethod = "DELETE"
                request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                // Best effort DELETE, ignore failure
                _ = try? await URLSession.shared.data(for: request)
            }
        }
        
        // Wipe local state regardless of server call outcome
        try? KeychainManager.clearToken()
        UserDefaults.standard.removeObject(forKey: Constants.Storage.deviceIdKey)
        
        self.deviceId = nil
        self.lastSyncedAt = nil
        self.isConnected = false
        self.isDisconnecting = false
    }
    
    private func getBaseURL() -> String {
        let fileManager = FileManager.default
        var baseURL = Constants.API.defaultBaseURL
        if let appSupport = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            let syncConfigPath = appSupport.appendingPathComponent(Constants.API.syncConfigPath)
            if let data = try? Data(contentsOf: syncConfigPath),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let configURL = json["base_url"] as? String {
                baseURL = configURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            }
        }
        return baseURL
    }
    
    private func startPolling() {
        stopPolling()
        // Immediately trigger once, then every 30 seconds
        pollSyncStatus()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.pollSyncStatus()
            }
        }
    }
    
    private func stopPolling() {
        pollTimer?.invalidate()
        pollTimer = nil
    }
    
    private func pollSyncStatus() {
        guard let token = try? KeychainManager.getToken() else { return }
        
        let baseURL = getBaseURL()
        guard let url = URL(string: "\(baseURL)\(Constants.API.checkpointPath)") else { return }
        
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        
        Task {
            do {
                let (data, response) = try await URLSession.shared.data(for: request)
                if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                    if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let rawDate = json["last_synced_at"] as? String {
                        
                        let formatter = ISO8601DateFormatter()
                        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                        if let date = formatter.date(from: rawDate) {
                            await MainActor.run { self.lastSyncedAt = date }
                        } else {
                            formatter.formatOptions = [.withInternetDateTime]
                            if let date = formatter.date(from: rawDate) {
                                await MainActor.run { self.lastSyncedAt = date }
                            }
                        }
                    }
                }
            } catch {
                print("Polling failed: \(error)")
            }
        }
    }
}
