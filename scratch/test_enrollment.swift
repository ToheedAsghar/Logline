import Foundation

@main
struct Tester {
    static func main() async {
        let vm = await EnrollmentViewModel()
        
        // 1. Force setup state without backend
        print("Injecting fake token and deviceId...")
        try? KeychainManager.storeToken("FAKE_TOKEN_404")
        UserDefaults.standard.set("fake-dev-404", forKey: Constants.Storage.deviceIdKey)
        
        await vm.checkExistingEnrollment()
        let isConnected = await vm.isConnected
        print("isConnected: \(isConnected)")
        
        // 2. Wait for polling to fail (backend is dead)
        print("Waiting 1 sec for poll to fail...")
        try? await Task.sleep(nanoseconds: 1_000_000_000)
        
        let isPollingError = await vm.isPollingError
        print("isPollingError set: \(isPollingError)")
        
        // 3. Test Disconnect (backend is dead)
        print("--- Disconnecting ---")
        await vm.disconnect()
        
        let isConnectedAfter = await vm.isConnected
        print("isConnected after: \(isConnectedAfter)")
        
        if let _ = try? KeychainManager.getToken() {
            print("Keychain is NOT empty (error)")
        } else {
            print("Keychain is empty after disconnect")
        }
        
        let storedIdAfter = UserDefaults.standard.string(forKey: Constants.Storage.deviceIdKey)
        print("UserDefaults deviceId after: \(storedIdAfter ?? "nil")")
    }
}
