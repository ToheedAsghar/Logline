import Foundation
import Security

let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "LoglineTracker",
    kSecAttrAccount as String: "SyncToken",
    kSecValueData as String: "dummy_token_123".data(using: .utf8)!
]
SecItemDelete(query as CFDictionary)
SecItemAdd(query as CFDictionary, nil)
