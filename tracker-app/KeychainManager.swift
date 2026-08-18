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
            kSecAttrAccount as String: account,
            kSecValueData as String: data
        ]

        // Delete any existing item first
        SecItemDelete(query as CFDictionary)

        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw KeychainError.unhandledError(status: status)
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
