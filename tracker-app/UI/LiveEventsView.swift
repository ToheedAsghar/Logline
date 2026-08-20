import SwiftUI
import AppKit

struct LiveEventsView: View {
    @StateObject private var viewModel = LiveEventsViewModel()
    @State private var isVisible = false
    
    // Provided by MainView to handle empty state presentation
    let isConnected: Bool
    
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Live Events")
                .font(Tokens.Fonts.ui(size: 14, weight: .semibold))
                .foregroundColor(Tokens.Colors.ink)
            
            if !isConnected {
                // Not Connected / Empty State
                VStack(spacing: 8) {
                    Text("Waiting for a session...")
                        .font(Tokens.Fonts.mono(size: 13))
                        .foregroundColor(Tokens.Colors.muted)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Tokens.Colors.cardBg)
                .cornerRadius(Tokens.Radius.card)
                .overlay(
                    RoundedRectangle(cornerRadius: Tokens.Radius.card)
                        .stroke(Tokens.Colors.border, lineWidth: 1)
                )
            } else {
                // Table View
                Table(viewModel.events) {
                    TableColumn("App") { event in
                        Text(event.appName)
                            .font(Tokens.Fonts.ui(size: 12))
                            .foregroundColor(Tokens.Colors.ink)
                    }
                    .width(150)
                    
                    TableColumn("Window Title") { event in
                        if let title = event.windowTitle, !title.isEmpty {
                            Text(title)
                                .font(Tokens.Fonts.ui(size: 12))
                                .foregroundColor(Tokens.Colors.ink)
                                .lineLimit(1)
                                .truncationMode(.tail)
                                .help(title) // Native tooltip
                        } else {
                            Text("—")
                                .font(Tokens.Fonts.ui(size: 12))
                                .foregroundColor(Tokens.Colors.muted)
                        }
                    }
                    // Flexible width naturally for Window Title
                    
                    TableColumn("Started") { event in
                        Text(formatTimeOnly(event.startedAt))
                            .font(Tokens.Fonts.mono(size: 12))
                            .foregroundColor(Tokens.Colors.ink)
                    }
                    .width(76)
                    
                    TableColumn("Ended") { event in
                        Text(formatTimeOnly(event.endedAt))
                            .font(Tokens.Fonts.mono(size: 12))
                            .foregroundColor(Tokens.Colors.ink)
                    }
                    .width(76)
                    
                    TableColumn("Idle") { event in
                        if event.isIdle {
                            HStack(spacing: 4) {
                                Circle()
                                    .fill(Tokens.Colors.idlePillDot)
                                    .frame(width: 4, height: 4)
                                Text("Idle")
                                    .font(Tokens.Fonts.ui(size: 11, weight: .medium))
                                    .foregroundColor(Tokens.Colors.idlePillText)
                            }
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Tokens.Colors.idlePillBg)
                            .cornerRadius(999)
                        } else {
                            Text("No")
                                .font(Tokens.Fonts.ui(size: 12))
                                .foregroundColor(Tokens.Colors.muted)
                        }
                    }
                    .width(58)
                }
                .tableStyle(.bordered)
                .cornerRadius(Tokens.Radius.card)
                .overlay(
                    RoundedRectangle(cornerRadius: Tokens.Radius.card)
                        .stroke(Tokens.Colors.border, lineWidth: 1)
                )
            }
        }
        .onAppear {
            isVisible = true
            if isConnected {
                viewModel.startAutoRefresh()
            }
        }
        .onChange(of: isConnected) { connected in
            if connected && isVisible {
                viewModel.startAutoRefresh()
            } else {
                viewModel.stopAutoRefresh()
            }
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
                    if isConnected {
                        viewModel.startAutoRefresh()
                    }
                }
            } else {
                if isVisible {
                    isVisible = false
                    viewModel.stopAutoRefresh()
                }
            }
        }
    }
    
    private func formatTimeOnly(_ isoString: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: isoString) {
            return formatAsTime(date)
        }
        
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: isoString) {
            return formatAsTime(date)
        }
        
        let df = DateFormatter()
        df.dateFormat = "yyyy-MM-dd HH:mm:ss"
        df.timeZone = TimeZone(secondsFromGMT: 0)
        if let date = df.date(from: isoString) {
            return formatAsTime(date)
        }
        
        // Manual extraction if parsing fails entirely: "2026-08-20T13:54:23"
        let parts = isoString.split(separator: "T")
        if parts.count == 2 {
            let timeStr = String(parts[1])
            return String(timeStr.prefix(5)) // "13:54"
        }
        return String(isoString.prefix(19)) // fallback
    }
    
    private func formatAsTime(_ date: Date) -> String {
        let timeFormatter = DateFormatter()
        timeFormatter.timeStyle = .short
        timeFormatter.dateStyle = .none
        timeFormatter.timeZone = TimeZone.current
        return timeFormatter.string(from: date)
    }
}
