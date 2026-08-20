import SwiftUI

struct MainView: View {
    @StateObject private var enrollmentVM = EnrollmentViewModel()
    
    var body: some View {
        VStack(spacing: 0) {
            // Header Bar
            HStack(spacing: 14) {
                // Spacer for traffic lights area
                Spacer().frame(width: 62)
                
                Spacer()
                
                // Centered App Title & Icon
                HStack(spacing: 9) {
                    if let image = NSImage(named: "AppIconPlaceholder.jpg") {
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
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(Color(hex: "#26231D"))
                        .tracking(-0.13)
                }
                
                Spacer()
                
                // Right aligned "LIVE" Pill (Only if connected)
                if enrollmentVM.isConnected {
                    HStack(spacing: 6) {
                        Circle()
                            .fill(Tokens.Colors.statusConnected)
                            .frame(width: 6, height: 6)
                        Text("LIVE")
                            .font(Tokens.Fonts.mono(size: 10, weight: .medium))
                            .tracking(0.4)
                            .foregroundColor(Color(hex: "#3F6B52"))
                    }
                    .padding(.horizontal, 9)
                    .frame(height: 22)
                    .background(Tokens.Colors.statusConnected.opacity(0.14))
                    .cornerRadius(11)
                    .frame(width: 62, alignment: .trailing)
                } else {
                    Spacer().frame(width: 62)
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
                EnrollmentView(enrollmentVM: enrollmentVM)
                
                LiveEventsView(isConnected: enrollmentVM.isConnected)
            }
            .padding(16)
        }
        .background(Tokens.Colors.windowBg)
        .frame(width: enrollmentVM.isConnected ? 760 : 520, height: 620)
        .onAppear {
            enrollmentVM.checkExistingEnrollment()
        }
        // Force the SwiftUI view to drive the window size natively
        .fixedSize()
    }
}
