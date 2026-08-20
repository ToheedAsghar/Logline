import Foundation
import Security

let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "LoglineTracker",
    kSecAttrAccount as String: "SyncToken",
    kSecReturnData as String: true,
    kSecMatchLimit as String: kSecMatchLimitOne
]

var dataTypeRef: AnyObject?
let status = SecItemCopyMatching(query as CFDictionary, &dataTypeRef)
if status == errSecSuccess, let data = dataTypeRef as? Data {
    print("TOKEN: \(String(data: data, encoding: .utf8)!)")
} else {
    print("STATUS: \(status)")
}
