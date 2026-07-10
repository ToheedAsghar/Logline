import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { IntegrationCard } from "../IntegrationCard";
import type { Integration } from "@/repositories/types";
import { ApiError } from "@/repositories/api/client";

// Mock the hooks
vi.mock("@/repositories/hooks", () => ({
  useConnectIntegration: vi.fn(),
  useDisconnectIntegration: vi.fn(),
}));

import { useConnectIntegration, useDisconnectIntegration } from "@/repositories/hooks";

const mockIntegration = (overrides: Partial<Integration>): Integration => ({
  id: 1,
  source: "github",
  status: "disconnected",
  last_synced_at: "2024-01-01T10:00:00Z",
  created_at: "2024-01-01T10:00:00Z",
  ...overrides,
});

describe("IntegrationCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders disconnected status correctly", () => {
    vi.mocked(useConnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null } as any);
    vi.mocked(useDisconnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false } as any);

    render(<IntegrationCard integration={mockIntegration({ status: "disconnected" })} />);
    
    expect(screen.getByText(/Disconnected/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });

  it("renders connected status correctly", () => {
    vi.mocked(useConnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null } as any);
    vi.mocked(useDisconnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false } as any);

    render(<IntegrationCard integration={mockIntegration({ status: "connected" })} />);
    
    expect(screen.getByText(/Connected/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
  });

  it("renders error status correctly", () => {
    vi.mocked(useConnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null } as any);
    vi.mocked(useDisconnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false } as any);

    render(<IntegrationCard integration={mockIntegration({ status: "error" })} />);
    
    expect(screen.getByText(/Error/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });

  it("handles Connect button click gracefully with a mocked 501 response", async () => {
    // 501 means "not available yet"
    const connectMutate = vi.fn();
    vi.mocked(useConnectIntegration).mockReturnValue({
      mutate: connectMutate,
      isPending: false,
      isError: true,
      error: new ApiError(501, { detail: "Not Implemented" }),
    } as any);
    vi.mocked(useDisconnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false } as any);

    render(<IntegrationCard integration={mockIntegration({ source: "github", status: "disconnected" })} />);
    
    const connectBtn = screen.getByRole("button", { name: "Connect" });
    fireEvent.click(connectBtn);
    
    expect(connectMutate).toHaveBeenCalledWith("github");
    
    // The "not available yet" message should be shown based on connectNotAvailable logic
    expect(screen.getByText(/isn't available yet — coming soon/)).toBeInTheDocument();
  });

  it("handles Connect button click with generic error", async () => {
    const connectMutate = vi.fn();
    vi.mocked(useConnectIntegration).mockReturnValue({
      mutate: connectMutate,
      isPending: false,
      isError: true,
      error: new Error("Random error"),
    } as any);
    vi.mocked(useDisconnectIntegration).mockReturnValue({ mutate: vi.fn(), isPending: false } as any);

    render(<IntegrationCard integration={mockIntegration({ source: "github", status: "disconnected" })} />);
    
    expect(screen.getByText(/Couldn't connect.*try again/)).toBeInTheDocument();
  });
});
