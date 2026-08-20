import SwiftUI

struct MainView: View {
    @StateObject private var enrollmentVM = EnrollmentViewModel()
    @State private var showSettings = false
    @State private var isTrackerRunning = ProcessManager.shared.isRunning
    let timer = Timer.publish(every: 1.0, on: .main, in: .common).autoconnect()
    
    var body: some View {
        VStack(spacing: 0) {
            // Header Bar
            HStack(spacing: 14) {
                // Spacer for traffic lights area
                Spacer().frame(width: 62)
                
                Spacer()
                
                // Centered App Title & Icon
                HStack(spacing: 9) {
                    if let image = NSImage(named: "AppIcon") {
                        Image(nsImage: image)
                            .resizable()
                            .frame(width: 17, height: 17)
                            .cornerRadius(5)
                            .opacity(enrollmentVM.isConnected ? 1.0 : 0.5)
                    } else {
                        // Fallback if asset is missing
                        RoundedRectangle(cornerRadius: 5)
                            .fill(Color.gray)
                            .frame(width: 17, height: 17)
                            .opacity(enrollmentVM.isConnected ? 1.0 : 0.5)
                    }
                    
                    Text("Logline Tracker")
                        .font(Tokens.Fonts.ui(size: 13, weight: .semibold))
                        .foregroundColor(Color(hex: "#26231D"))
                        .tracking(-0.13)
                }
                
                Spacer()
                
                // Right aligned controls
                HStack(spacing: 12) {
                    // Local Tracker Start/Stop
                    Button(action: {
                        if ProcessManager.shared.isRunning {
                            ProcessManager.shared.terminateTrackerDaemon()
                        } else {
                            do {
                                try ProcessManager.shared.startTrackerDaemon()
                            } catch {
                                print("Failed to start tracker: \(error)")
                            }
                        }
                    }) {
                        HStack(spacing: 6) {
                            Circle()
                                .fill(isTrackerRunning ? Tokens.Colors.statusConnected : Tokens.Colors.muted)
                                .frame(width: 6, height: 6)
                            Text(isTrackerRunning ? "TRACKING" : "STOPPED")
                                .font(Tokens.Fonts.mono(size: 10, weight: .medium))
                                .tracking(0.4)
                                .foregroundColor(isTrackerRunning ? Color(hex: "#3F6B52") : Tokens.Colors.muted)
                        }
                        .padding(.horizontal, 9)
                        .frame(height: 22)
                        .background(isTrackerRunning ? Tokens.Colors.statusConnected.opacity(0.14) : Color.black.opacity(0.05))
                        .cornerRadius(11)
                    }
                    .buttonStyle(PlainButtonStyle())
                    .help(isTrackerRunning ? "Stop local capture" : "Start local capture")
                    
                    // Settings Gear
                    Button(action: {
                        withAnimation {
                            showSettings.toggle()
                        }
                    }) {
                        Image(systemName: "gearshape.fill")
                            .font(.system(size: 14))
                            .foregroundColor(showSettings ? Tokens.Colors.brandGreen : Tokens.Colors.muted)
                            .frame(width: 22, height: 22)
                            .background(showSettings ? Tokens.Colors.brandGreen.opacity(0.14) : Color.clear)
                            .cornerRadius(5)
                    }
                    .buttonStyle(PlainButtonStyle())
                    .help("Settings")
                }
            }
            .frame(height: 48)
            .padding(.horizontal, 16)
            .background(Color(hex: "#F1EDE2"))
            .overlay(
                Rectangle()
                    .frame(height: 0.5)
                    .foregroundColor(Color(hex: "#DDD8CB"))
                , alignment: .bottom
            )
            
            // Main Content Area
            VStack(spacing: 14) {
                if showSettings {
                    EnrollmentView(enrollmentVM: enrollmentVM, showSettings: $showSettings)
                    Spacer()
                } else {
                    LiveEventsView(isConnected: enrollmentVM.isConnected)
                }
            }
            .padding(16)
        }
        .background(Tokens.Colors.windowBg)
        .frame(width: showSettings ? 520 : (enrollmentVM.isConnected ? 760 : 520), height: 620)
        .onAppear {
            enrollmentVM.checkExistingEnrollment()
        }
        .onReceive(timer) { _ in
            isTrackerRunning = ProcessManager.shared.isRunning
        }
        // Force the SwiftUI view to drive the window size natively
        .fixedSize()
    }
}
