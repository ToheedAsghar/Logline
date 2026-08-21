import Foundation
import Security

public enum KeychainManager {
    private static let service = "LoglineTracker"
    private static let account = "SyncToken"

    public static func storeToken(_ token: String) throws {
        guard let data = token.data(using: .utf8) else {
            throw KeychainError.invalidData
        }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        
        let attributesToUpdate: [String: Any] = [
            kSecValueData as String: data
        ]

        var status = SecItemUpdate(query as CFDictionary, attributesToUpdate as CFDictionary)
        
        if status == errSecItemNotFound {
            var addQuery = query
            addQuery[kSecValueData as String] = data
            status = SecItemAdd(addQuery as CFDictionary, nil)
        }

        guard status == errSecSuccess else {
            throw KeychainError.unhandledError(status: status)
        }
    }

    public static func migrateLegacyToken() {
        // Find legacy file
        let fileManager = FileManager.default
        guard let appSupportURL = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else { return }
        let loglineURL = appSupportURL.appendingPathComponent("Logline")
        let legacyTokenURL = loglineURL.appendingPathComponent("device_token")
        
        guard fileManager.fileExists(atPath: legacyTokenURL.path) else { return }
        
        do {
            let tokenString = try String(contentsOf: legacyTokenURL, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            if !tokenString.isEmpty {
                try storeToken(tokenString)
                print("Migrated legacy device_token to Keychain.")
            }
            try fileManager.removeItem(at: legacyTokenURL)
            print("Deleted legacy device_token file.")
        } catch {
            print("Failed to migrate legacy device_token: \(error)")
        }
    }

    public static func getToken() throws -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]

        var dataTypeRef: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &dataTypeRef)

        if status == errSecItemNotFound {
            return nil
        }
        
        guard status == errSecSuccess,
              let data = dataTypeRef as? Data,
              let token = String(data: data, encoding: .utf8) else {
            throw KeychainError.unhandledError(status: status)
        }

        return token
    }

    public static func clearToken() throws {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]

        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError.unhandledError(status: status)
        }
    }
}

public enum KeychainError: Error, LocalizedError {
    case invalidData
    case unhandledError(status: OSStatus)

    public var errorDescription: String? {
        switch self {
        case .invalidData:
            return "Failed to convert token to data."
        case .unhandledError(let status):
            if let errorMessage = SecCopyErrorMessageString(status, nil) {
                return "Keychain error: \(errorMessage) (\(status))"
            } else {
                return "Keychain error: \(status)"
            }
        }
    }
}
