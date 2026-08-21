import Foundation

@MainActor
public class LiveEventsViewModel: ObservableObject {
    @Published public var events: [TrackerEvent] = []
    
    private let reader = DatabaseReader()
    private var refreshTask: Task<Void, Never>?
    
    public init() {}
    
    public func startAutoRefresh() {
        guard refreshTask == nil else { return }
        print("LiveEventsViewModel: startAutoRefresh() called")
        fflush(stdout)
        
        refreshTask = Task { @MainActor in
            while !Task.isCancelled {
                self.fetchEvents()
                do {
                    try await Task.sleep(nanoseconds: 15_000_000_000)
                } catch {
                    break
                }
            }
        }
    }
    
    public func stopAutoRefresh() {
        guard refreshTask != nil else { return }
        print("LiveEventsViewModel: stopAutoRefresh() called")
        fflush(stdout)
        refreshTask?.cancel()
        refreshTask = nil
    }
    
    private func fetchEvents() {
        print("LiveEventsViewModel: Fetching events from DB...")
        fflush(stdout)
        self.events = reader.fetchRecentEvents(limit: 500)
    }
}
