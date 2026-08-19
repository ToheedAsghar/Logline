import SwiftUI

struct MainView: View {
    @StateObject private var enrollmentVM = EnrollmentViewModel()
    @State private var tokenInput: String = ""
    
    var body: some View {
        VStack(spacing: 24) {
            // Placeholder: Enrollment
            VStack(alignment: .leading, spacing: 8) {
                Text("Enrollment")
                    .font(.headline)
                    .foregroundColor(Tokens.Colors.SwiftUI.text)
                
                if enrollmentVM.isConnected {
                    HStack {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(Tokens.Colors.SwiftUI.accent)
                        Text("Connected\(enrollmentVM.deviceId != nil ? " as \(enrollmentVM.deviceId!)" : "")")
                            .foregroundColor(Tokens.Colors.SwiftUI.text)
                        
                        Spacer()
                        
                        Button(action: {
                            Task {
                                await enrollmentVM.disconnect()
                            }
                        }) {
                            Text(enrollmentVM.isDisconnecting ? "Disconnecting..." : "Disconnect")
                        }
                        .disabled(enrollmentVM.isDisconnecting)
                        .buttonStyle(BorderedButtonStyle())
                    }
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Tokens.Colors.SwiftUI.surface)
                    .cornerRadius(Tokens.Radius.md)
                    .overlay(
                        RoundedRectangle(cornerRadius: Tokens.Radius.md)
                            .stroke(Tokens.Colors.SwiftUI.border, lineWidth: 1)
                    )
                } else {
                    HStack {
                        SecureField("Token...", text: $tokenInput)
                            .textFieldStyle(RoundedBorderTextFieldStyle())
                            .disabled(enrollmentVM.isConnecting)
                        
                        Button(enrollmentVM.isConnecting ? "Connecting..." : "Connect") {
                            Task {
                                await enrollmentVM.connect(token: tokenInput)
                            }
                        }
                        .buttonStyle(BorderedProminentButtonStyle())
                        .tint(Tokens.Colors.SwiftUI.accent)
                        .disabled(enrollmentVM.isConnecting || tokenInput.isEmpty)
                    }
                    .padding()
                    .background(Tokens.Colors.SwiftUI.surface)
                    .cornerRadius(Tokens.Radius.md)
                    .overlay(
                        RoundedRectangle(cornerRadius: Tokens.Radius.md)
                            .stroke(Tokens.Colors.SwiftUI.border, lineWidth: 1)
                    )
                    
                    if let errorMessage = enrollmentVM.errorMessage {
                        Text(errorMessage)
                            .font(.caption)
                            .foregroundColor(Tokens.Colors.SwiftUI.danger)
                            .padding(.top, 4)
                    }
                }
            }
            
            // Placeholder: Sync Status
            VStack(alignment: .leading, spacing: 8) {
                Text("Sync Status")
                    .font(.headline)
                    .foregroundColor(Tokens.Colors.SwiftUI.text)
                
                HStack {
                    if enrollmentVM.isPollingError {
                        Circle()
                            .fill(Tokens.Colors.SwiftUI.danger)
                            .frame(width: 10, height: 10)
                        Text("Sync Error")
                            .foregroundColor(Tokens.Colors.SwiftUI.danger)
                    } else if let lastSynced = enrollmentVM.lastSyncedAt {
                        Circle()
                            .fill(Tokens.Colors.SwiftUI.accent)
                            .frame(width: 10, height: 10)
                        
                        let formatter = RelativeDateTimeFormatter()
                        formatter.unitsStyle = .full
                        let dateStr = formatter.localizedString(for: lastSynced, relativeTo: Date())
                        
                        Text("Synced \(dateStr)")
                            .foregroundColor(Tokens.Colors.SwiftUI.text)
                    } else if enrollmentVM.isConnected {
                        Circle()
                            .fill(Tokens.Colors.SwiftUI.accentSoft)
                            .frame(width: 10, height: 10)
                        Text("Waiting for first sync...")
                            .foregroundColor(Tokens.Colors.SwiftUI.muted)
                    } else {
                        Circle()
                            .fill(Tokens.Colors.SwiftUI.danger)
                            .frame(width: 10, height: 10)
                        Text("Not Connected")
                            .foregroundColor(Tokens.Colors.SwiftUI.muted)
                    }
                    Spacer()
                    Button("Sync Now") {}
                }
                .padding()
                .background(Tokens.Colors.SwiftUI.surface)
                .cornerRadius(Tokens.Radius.md)
                .overlay(
                    RoundedRectangle(cornerRadius: Tokens.Radius.md)
                        .stroke(Tokens.Colors.SwiftUI.border, lineWidth: 1)
                )
            }
            
            // Placeholder: Events View
            VStack(alignment: .leading, spacing: 8) {
                Text("Recent Events")
                    .font(.headline)
                    .foregroundColor(Tokens.Colors.SwiftUI.text)
                
                ScrollView {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(0..<3) { i in
                            HStack {
                                Text("Code")
                                    .font(.caption)
                                    .padding(4)
                                    .background(Tokens.Colors.SwiftUI.surface2)
                                    .cornerRadius(Tokens.Radius.xs)
                                Text("tracker/main.py")
                                    .font(.subheadline)
                                Spacer()
                                Text("10:42 AM")
                                    .font(.caption)
                                    .foregroundColor(Tokens.Colors.SwiftUI.muted)
                            }
                            .padding(8)
                            .background(Tokens.Colors.SwiftUI.surface)
                            .cornerRadius(Tokens.Radius.sm)
                        }
                    }
                    .padding(8)
                }
                .frame(height: 150)
                .background(Tokens.Colors.SwiftUI.surface)
                .cornerRadius(Tokens.Radius.md)
                .overlay(
                    RoundedRectangle(cornerRadius: Tokens.Radius.md)
                        .stroke(Tokens.Colors.SwiftUI.border, lineWidth: 1)
                )
            }
        }
        .padding(24)
        .background(Tokens.Colors.SwiftUI.bg)
        .frame(minWidth: 400, minHeight: 500)
        .onAppear {
            enrollmentVM.checkExistingEnrollment()
        }
    }
}
