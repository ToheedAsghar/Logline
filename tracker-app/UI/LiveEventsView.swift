import SwiftUI
import AppKit

struct LiveEventsView: View {
    @StateObject private var viewModel = LiveEventsViewModel()
    @State private var isVisible = false
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Live Events")
                .font(.headline)
                .foregroundColor(Tokens.Colors.SwiftUI.text)
            
            Table(viewModel.events) {
                TableColumn("App", value: \.appName)
                TableColumn("Window Title") { event in
                    Text(event.windowTitle ?? "")
                }
                TableColumn("Started", value: \.startedAt)
                TableColumn("Ended", value: \.endedAt)
                TableColumn("Idle") { event in
                    Text(event.isIdle ? "Yes" : "No")
                        .foregroundColor(event.isIdle ? Tokens.Colors.SwiftUI.muted : Tokens.Colors.SwiftUI.text)
                }
            }
            .tableStyle(.bordered)
            .cornerRadius(Tokens.Radius.md)
        }
        .onAppear {
            isVisible = true
            viewModel.startAutoRefresh()
        }
        .onDisappear {
            isVisible = false
            viewModel.stopAutoRefresh()
        }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didChangeOcclusionStateNotification)) { notification in
            guard let window = notification.object as? NSWindow,
                  window.title == "Logline Tracker" else { return }
            
            if window.occlusionState.contains(.visible) {
                if !isVisible {
                    isVisible = true
                    viewModel.startAutoRefresh()
                }
            } else {
                if isVisible {
                    isVisible = false
                    viewModel.stopAutoRefresh()
                }
            }
        }
    }
}
