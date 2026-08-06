import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Settings from "../Settings";
import type { Integration } from "@/repositories/types";

vi.mock("@/repositories/hooks", () => ({
  useIntegrations: vi.fn(),
  useConnectIntegration: vi.fn(),
  useDisconnectIntegration: vi.fn(),
  useTrackerSyncStatus: vi.fn(),
  useEnrollTrackerDevice: vi.fn(),
}));

import {
  useIntegrations,
  useConnectIntegration,
  useDisconnectIntegration,
  useTrackerSyncStatus,
  useEnrollTrackerDevice,
} from "@/repositories/hooks";


const mockIntegration = (overrides: Partial<Integration>): Integration => ({
  id: 1,
  source: "github",
  status: "disconnected",
  last_synced_at: null,
  created_at: "2024-01-01T10:00:00Z",
  ...overrides,
});

describe("Settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useConnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null } as unknown as ReturnType<typeof useConnectIntegration>);
    vi.mocked(useDisconnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false } as unknown as ReturnType<typeof useDisconnectIntegration>);
    vi.mocked(useEnrollTrackerDevice).mockReturnValue({ mutate: vi.fn(), isPending: false } as unknown as ReturnType<typeof useEnrollTrackerDevice>);
    vi.mocked(useTrackerSyncStatus).mockReturnValue({
      data: { last_synced_at: new Date().toISOString(), device_count: 1 },
      isError: false,
    } as unknown as ReturnType<typeof useTrackerSyncStatus>);
  });

  it("shows a loading state while integrations are being fetched", () => {
    vi.mocked(useIntegrations).mockReturnValue({ isLoading: true, isError: false, data: undefined } as unknown as ReturnType<typeof useIntegrations>);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(screen.getByText(/Loading integrations/)).toBeInTheDocument();
  });

  it("shows an error state when the integrations request fails", () => {
    vi.mocked(useIntegrations).mockReturnValue({ isLoading: false, isError: true, data: undefined } as unknown as ReturnType<typeof useIntegrations>);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(screen.getByText(/Couldn't load integrations/)).toBeInTheDocument();
  });

  it("renders a card per known source, filling in a disconnected placeholder for ones the backend hasn't created a row for", () => {
    vi.mocked(useIntegrations).mockReturnValue({
      isLoading: false,
      isError: false,
      data: [mockIntegration({ source: "github", status: "connected", last_synced_at: "2024-01-01T10:00:00Z" })],
    } as unknown as ReturnType<typeof useIntegrations>);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.getByText("Jira")).toBeInTheDocument();
    expect(screen.getByText("Google Calendar")).toBeInTheDocument();
    expect(screen.getByText("Slack")).toBeInTheDocument();
    expect(screen.getByText("1/4 active")).toBeInTheDocument();
  });

  it("surfaces a needs-attention count when an integration has errored", () => {
    vi.mocked(useIntegrations).mockReturnValue({
      isLoading: false,
      isError: false,
      data: [
        mockIntegration({ source: "github", status: "connected" }),
        mockIntegration({ id: 2, source: "calendar", status: "error" }),
      ],
    } as unknown as ReturnType<typeof useIntegrations>);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(screen.getByText("1 needs attention")).toBeInTheDocument();
  });

  it("omits the needs-attention indicator when nothing has errored", () => {
    vi.mocked(useIntegrations).mockReturnValue({
      isLoading: false,
      isError: false,
      data: [mockIntegration({ source: "github", status: "connected" })],
    } as unknown as ReturnType<typeof useIntegrations>);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(screen.queryByText(/needs attention/)).not.toBeInTheDocument();
  });

  it("parses OAuth callback query parameters and renders a success notice", () => {
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: new URL("http://localhost/settings?integration=github&status=connected"),
    });

    vi.mocked(useIntegrations).mockReturnValue({
      isLoading: false,
      isError: false,
      data: [mockIntegration({ source: "github", status: "connected" })],
    } as unknown as ReturnType<typeof useIntegrations>);

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(screen.getByText("Successfully connected GitHub!")).toBeInTheDocument();
    Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
  });

  it("surfaces tracker sync freshness alongside the integrations", () => {
    vi.mocked(useIntegrations).mockReturnValue({ isLoading: false, isError: false, data: [] } as unknown as ReturnType<typeof useIntegrations>);
    vi.mocked(useTrackerSyncStatus).mockReturnValue({
      data: { last_synced_at: new Date(Date.now() - 3 * 60_000).toISOString(), device_count: 1 },
      isError: false,
    } as unknown as ReturnType<typeof useTrackerSyncStatus>);

    render(<Settings />);

    expect(screen.getByText(/Tracker last synced 3m ago/)).toBeInTheDocument();
  });

  it("says so when the tracker sync status can't be loaded, rather than showing nothing", () => {
    vi.mocked(useIntegrations).mockReturnValue({ isLoading: false, isError: false, data: [] } as unknown as ReturnType<typeof useIntegrations>);
    vi.mocked(useTrackerSyncStatus).mockReturnValue({ data: undefined, isError: true } as unknown as ReturnType<typeof useTrackerSyncStatus>);

    render(<Settings />);

    expect(screen.getByText(/Couldn't check tracker sync status/)).toBeInTheDocument();
  });

});
