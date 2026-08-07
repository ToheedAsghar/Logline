import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import OAuthCallback from "../OAuthCallback";
import { AUTH_STRINGS } from "@/constants/authMessages";
import { googleExchange } from "@/repositories/api/auth";
import { useSession } from "@/context/SessionContext";

vi.mock("@/repositories/api/auth", () => ({
  googleExchange: vi.fn(),
}));

vi.mock("@/context/SessionContext", () => ({
  useSession: vi.fn(),
}));

describe("OAuthCallback", () => {
  const mockLoginWithToken = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useSession).mockReturnValue({
      loginWithToken: mockLoginWithToken,
    } as unknown as ReturnType<typeof useSession>);
  });

  it("exchanges code for access_token and logs in when code query param is present", async () => {
    vi.mocked(googleExchange).mockResolvedValue({ access_token: "mock-jwt-token", token_type: "bearer" });

    render(
      <MemoryRouter initialEntries={["/auth/google/callback?code=valid-code"]}>
        <Routes>
          <Route path="/auth/google/callback" element={<OAuthCallback />} />
          <Route path="/" element={<div>Home Page</div>} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(googleExchange).toHaveBeenCalledWith("valid-code");
      expect(mockLoginWithToken).toHaveBeenCalledWith("mock-jwt-token");
      expect(screen.getByText("Home Page")).toBeInTheDocument();
    });
  });

  it("shows localized GOOGLE_SSO_FAILED message on exchange failure rather than raw error text", async () => {
    vi.mocked(googleExchange).mockRejectedValue(new Error("Raw backend exception stringified JSON"));

    render(
      <MemoryRouter initialEntries={["/auth/google/callback?code=invalid-code"]}>
        <Routes>
          <Route path="/auth/google/callback" element={<OAuthCallback />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText(AUTH_STRINGS.GOOGLE_SSO_FAILED)).toBeInTheDocument();
      expect(screen.queryByText("Raw backend exception stringified JSON")).not.toBeInTheDocument();
    });
  });

  it("does not log in directly from a ?token= query parameter", async () => {
    render(
      <MemoryRouter initialEntries={["/auth/google/callback?token=raw-url-token"]}>
        <Routes>
          <Route path="/auth/google/callback" element={<OAuthCallback />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockLoginWithToken).not.toHaveBeenCalled();
      expect(googleExchange).not.toHaveBeenCalled();
      expect(screen.getByText(AUTH_STRINGS.GOOGLE_SSO_FAILED)).toBeInTheDocument();
    });
  });
});
