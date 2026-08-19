import Foundation

@MainActor
class EnrollmentViewModel: ObservableObject {
    @Published var isConnected: Bool = false
    @Published var deviceId: String? = nil
    @Published var lastSyncedAt: Date? = nil
    @Published var errorMessage: String? = nil
    @Published var isConnecting: Bool = false
    
    func checkExistingEnrollment() {
        if let _ = try? KeychainManager.getToken() {
            isConnected = true
            errorMessage = nil
            // In a real app we'd fetch the checkpoint immediately, 
            // but we'll leave that for the polling task.
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
                    
                    // Success: store token
                    try KeychainManager.storeToken(token)
                    
                    self.isConnected = true
                    self.errorMessage = nil
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
}
