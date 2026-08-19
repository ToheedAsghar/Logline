import SwiftUI

struct MainView: View {
    var body: some View {
        VStack(spacing: 24) {
            // Placeholder: Enrollment
            VStack(alignment: .leading, spacing: 8) {
                Text("Enrollment")
                    .font(.headline)
                    .foregroundColor(Tokens.Colors.SwiftUI.text)
                
                HStack {
                    SecureField("Token...", text: .constant(""))
                        .textFieldStyle(RoundedBorderTextFieldStyle())
                    Button("Connect") {}
                        .buttonStyle(BorderedProminentButtonStyle())
                        .tint(Tokens.Colors.SwiftUI.accent)
                }
                .padding()
                .background(Tokens.Colors.SwiftUI.surface)
                .cornerRadius(Tokens.Radius.md)
                .overlay(
                    RoundedRectangle(cornerRadius: Tokens.Radius.md)
                        .stroke(Tokens.Colors.SwiftUI.border, lineWidth: 1)
                )
            }
            
            // Placeholder: Sync Status
            VStack(alignment: .leading, spacing: 8) {
                Text("Sync Status")
                    .font(.headline)
                    .foregroundColor(Tokens.Colors.SwiftUI.text)
                
                HStack {
                    Circle()
                        .fill(Tokens.Colors.SwiftUI.accent)
                        .frame(width: 10, height: 10)
                    Text("Synced 2 mins ago")
                        .foregroundColor(Tokens.Colors.SwiftUI.text)
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
    }
}
