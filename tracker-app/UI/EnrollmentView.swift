import SwiftUI

struct EnrollmentView: View {
    @ObservedObject var enrollmentVM: EnrollmentViewModel
    @Binding var showSettings: Bool
    @State private var tokenInput: String = ""
    
    var body: some View {
        VStack(spacing: 20) {
            // Settings Header
            HStack {
                Text("Settings")
                    .font(Tokens.Fonts.ui(size: 16, weight: .semibold))
                    .foregroundColor(Tokens.Colors.ink)
                Spacer()
                Button(action: {
                    withAnimation {
                        showSettings = false
                    }
                }) {
                    Image(systemName: "xmark")
                        .font(.system(size: 14))
                        .foregroundColor(Tokens.Colors.muted)
                }
                .buttonStyle(PlainButtonStyle())
            }
            .padding(.bottom, 10)
            
            if enrollmentVM.isConnected {
                // Connected: Stacked layout
                VStack(spacing: 14) {
                // Enrollment Card
                VStack(alignment: .leading, spacing: 10) {
                    Text("Enrollment")
                        .font(Tokens.Fonts.ui(size: 13, weight: .semibold))
                        .foregroundColor(Tokens.Colors.ink)
                    
                    HStack(spacing: 12) {
                        Circle()
                            .fill(Tokens.Colors.brandGreen)
                            .frame(width: 14, height: 14)
                            .overlay(
                                Image(systemName: "checkmark")
                                    .font(.system(size: 8, weight: .bold))
                                    .foregroundColor(.white)
                            )
                        
                        Text("Connected")
                            .font(Tokens.Fonts.ui(size: 13))
                            .foregroundColor(Tokens.Colors.ink)
                            .lineLimit(1)
                            .help("Device ID: \(enrollmentVM.deviceId ?? "Unknown")")
                        
                        Spacer()
                        
                        Button(action: {
                            Task {
                                await enrollmentVM.disconnect()
                            }
                        }) {
                            Text(enrollmentVM.isDisconnecting ? "Disconnecting..." : "Disconnect")
                                .font(Tokens.Fonts.ui(size: 12, weight: .medium))
                        }
                        .disabled(enrollmentVM.isDisconnecting)
                        .buttonStyle(SecondaryButtonStyle())
                    }
                    .padding(14)
                    .background(Tokens.Colors.cardBg)
                    .cornerRadius(Tokens.Radius.card)
                    .overlay(
                        RoundedRectangle(cornerRadius: Tokens.Radius.card)
                            .stroke(Tokens.Colors.border, lineWidth: 1)
                    )
                }
                .frame(maxWidth: .infinity)
                
                // Sync Status Card
                VStack(alignment: .leading, spacing: 10) {
                    Text("Sync Status")
                        .font(Tokens.Fonts.ui(size: 13, weight: .semibold))
                        .foregroundColor(Tokens.Colors.ink)
                    
                    HStack(spacing: 12) {
                        Circle()
                            .fill(statusColor)
                            .frame(width: 10, height: 10)
                        
                        Text(statusText)
                            .font(Tokens.Fonts.ui(size: 13))
                            .foregroundColor(Tokens.Colors.ink)
                        
                        Spacer()
                        
                        Button(action: {
                            // "Sync Now" action (placeholder logic as it just triggers a manual poll)
                            NotificationCenter.default.post(name: NSNotification.Name("TriggerManualSync"), object: nil)
                        }) {
                            Text("Sync Now")
                                .font(Tokens.Fonts.ui(size: 12, weight: .medium))
                        }
                        .buttonStyle(SecondaryButtonStyle())
                        .disabled(enrollmentVM.isPollingError)
                    }
                    .padding(14)
                    .background(Tokens.Colors.cardBg)
                    .cornerRadius(Tokens.Radius.card)
                    .overlay(
                        RoundedRectangle(cornerRadius: Tokens.Radius.card)
                            .stroke(Tokens.Colors.border, lineWidth: 1)
                    )
                }
                .frame(maxWidth: .infinity)
            }
        } else {
            // Not Connected: Centered large card
            VStack(alignment: .leading, spacing: 10) {
                Text("Enrollment")
                    .font(Tokens.Fonts.ui(size: 13, weight: .semibold))
                    .foregroundColor(Tokens.Colors.ink)
                
                VStack(spacing: 16) {
                    Text("Connect this Mac to your Logline workspace to start streaming development events.")
                        .font(Tokens.Fonts.ui(size: 14))
                        .foregroundColor(Tokens.Colors.body)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                        .padding(.top, 16)
                    
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 0) {
                            SecureField("Paste connection token...", text: $tokenInput)
                                .font(Tokens.Fonts.mono(size: 13))
                                .textFieldStyle(PlainTextFieldStyle())
                                .padding(.horizontal, 12)
                                .padding(.vertical, 8)
                                .background(Tokens.Colors.windowBg)
                                .cornerRadius(Tokens.Radius.control)
                                .overlay(
                                    RoundedRectangle(cornerRadius: Tokens.Radius.control)
                                        .stroke(Tokens.Colors.border, lineWidth: 1)
                                )
                            
                            Button(action: {
                                Task {
                                    await enrollmentVM.connect(token: tokenInput)
                                }
                            }) {
                                Text(enrollmentVM.isConnecting ? "Connecting..." : "Connect")
                                    .font(Tokens.Fonts.ui(size: 13, weight: .medium))
                            }
                            .buttonStyle(PrimaryButtonStyle())
                            .disabled(enrollmentVM.isConnecting || tokenInput.isEmpty)
                            .padding(.leading, 8)
                        }
                        
                        if let errorMessage = enrollmentVM.errorMessage {
                            Text(errorMessage)
                                .font(Tokens.Fonts.ui(size: 12))
                                .foregroundColor(Tokens.Colors.statusFailed)
                                .padding(.leading, 4)
                        }
                    }
                    
                    // Offline Status Footer
                    HStack(spacing: 6) {
                        Circle()
                            .fill(Tokens.Colors.statusNotConnected)
                            .frame(width: 8, height: 8)
                        Text("Not connected")
                            .font(Tokens.Fonts.ui(size: 12))
                            .foregroundColor(Tokens.Colors.muted)
                    }
                    .padding(.bottom, 16)
                }
                .padding(24)
                .background(Tokens.Colors.cardBg)
                .cornerRadius(Tokens.Radius.card)
                .overlay(
                    RoundedRectangle(cornerRadius: Tokens.Radius.card)
                        .stroke(Tokens.Colors.border, lineWidth: 1)
                )
            }
        }
        }
        .padding(.horizontal, 16)
    }
    
    // Derived properties for Sync Status
    private var statusColor: Color {
        if enrollmentVM.isPollingError {
            return Tokens.Colors.statusFailed
        } else if enrollmentVM.lastSyncedAt != nil {
            return Tokens.Colors.statusConnected
        } else {
            return Tokens.Colors.statusSyncing // Waiting for first sync...
        }
    }
    
    private var statusText: String {
        if enrollmentVM.isPollingError {
            return "Sync Failed"
        } else if let lastSynced = enrollmentVM.lastSyncedAt {
            return "Synced \(formatRelativeDate(lastSynced))"
        } else {
            return "Waiting for first sync..."
        }
    }
    
    private func formatRelativeDate(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

// Custom Button Styles
struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(configuration.isPressed ? Tokens.Colors.primaryButtonHover : Tokens.Colors.primaryButton)
            .foregroundColor(.white)
            .cornerRadius(Tokens.Radius.control)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .background(Tokens.Colors.border)
            .foregroundColor(Tokens.Colors.ink)
            .cornerRadius(Tokens.Radius.control)
            .opacity(configuration.isPressed ? 0.7 : 1.0)
    }
}
