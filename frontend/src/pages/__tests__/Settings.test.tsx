import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Settings from "../Settings";
import type { Integration } from "@/repositories/types";

vi.mock("@/repositories/hooks", () => ({
  useIntegrations: vi.fn(),
  useConnectIntegration: vi.fn(),
  useDisconnectIntegration: vi.fn(),
}));

import { useIntegrations, useConnectIntegration, useDisconnectIntegration } from "@/repositories/hooks";

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
    vi.mocked(useConnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null } as any);
    vi.mocked(useDisconnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false } as any);
  });

  it("shows a loading state while integrations are being fetched", () => {
    vi.mocked(useIntegrations).mockReturnValue({ isLoading: true, isError: false, data: undefined } as any);

    render(<Settings />);

    expect(screen.getByText(/Loading integrations/)).toBeInTheDocument();
  });

  it("shows an error state when the integrations request fails", () => {
    vi.mocked(useIntegrations).mockReturnValue({ isLoading: false, isError: true, data: undefined } as any);

    render(<Settings />);

    expect(screen.getByText(/Couldn't load integrations/)).toBeInTheDocument();
  });

  it("renders a card per known source, filling in a disconnected placeholder for ones the backend hasn't created a row for", () => {
    vi.mocked(useIntegrations).mockReturnValue({
      isLoading: false,
      isError: false,
      data: [mockIntegration({ source: "github", status: "connected", last_synced_at: "2024-01-01T10:00:00Z" })],
    } as any);

    render(<Settings />);

    // github, jira, calendar, slack — one card each, even though only github has a real row.
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
    } as any);

    render(<Settings />);

    expect(screen.getByText("1 needs attention")).toBeInTheDocument();
  });

  it("omits the needs-attention indicator when nothing has errored", () => {
    vi.mocked(useIntegrations).mockReturnValue({
      isLoading: false,
      isError: false,
      data: [mockIntegration({ source: "github", status: "connected" })],
    } as any);

    render(<Settings />);

    expect(screen.queryByText(/needs attention/)).not.toBeInTheDocument();
  });
});
