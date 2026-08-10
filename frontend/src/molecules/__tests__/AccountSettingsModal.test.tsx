import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AccountSettingsModal } from "../AccountSettingsModal";
import { useSession } from "@/context/SessionContext";
import { useTheme } from "@/context/ThemeContext";
import { me, setTimezone } from "@/repositories/api/auth";
import type { UserResponse } from "@/repositories/types";

vi.mock("@/context/SessionContext", () => ({
  useSession: vi.fn(),
}));

vi.mock("@/context/ThemeContext", () => ({
  useTheme: vi.fn(),
}));

vi.mock("@/repositories/api/auth", () => ({
  me: vi.fn(),
  setTimezone: vi.fn(),
}));

const userResponse = (overrides: Partial<UserResponse> = {}): UserResponse => ({
  id: 1,
  email: "test@example.com",
  name: "Test User",
  default_channel: null,
  timezone: null,
  created_at: "2026-08-01T00:00:00Z",
  ...overrides,
});

describe("AccountSettingsModal", () => {
  const mockLogout = vi.fn();
  const mockSetLight = vi.fn();
  const mockSetDark = vi.fn();
  const mockOnClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useSession).mockReturnValue({ logout: mockLogout } as any);
    vi.mocked(useTheme).mockReturnValue({ theme: "light", setLight: mockSetLight, setDark: mockSetDark });
    vi.mocked(me).mockResolvedValue({ id: "user-1", email: "test@example.com", name: "Test User" } as any);
    vi.mocked(setTimezone).mockResolvedValue(userResponse({ timezone: "Asia/Karachi" }));
  });

  it("renders profile fields and populates from mocked GET /auth/me", async () => {
    render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("Test User")).toBeInTheDocument();
      expect(screen.getByDisplayValue("test@example.com")).toBeInTheDocument();
    });

    expect(screen.getByText("Display name")).toBeInTheDocument();
    expect(screen.getByText("Work email")).toBeInTheDocument();
  });

  it("disables the name, email, and channel fields since none of them save", async () => {
    render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("Test User")).toBeInTheDocument();
    });

    expect(screen.getByDisplayValue("Test User")).toBeDisabled();
    expect(screen.getByDisplayValue("test@example.com")).toBeDisabled();
    expect(screen.getByLabelText("Default standup channel")).toBeDisabled();
  });

  it("does not offer Handle or Role fields, which have no backing data at all", async () => {
    render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

    await waitFor(() => expect(screen.getByDisplayValue("Test User")).toBeInTheDocument());

    expect(screen.queryByText("Handle")).not.toBeInTheDocument();
    expect(screen.queryByText("Role")).not.toBeInTheDocument();
  });

  it("shows the account's real default channel instead of a false blank", async () => {
    vi.mocked(me).mockResolvedValue(userResponse({ default_channel: "genesis-standups" }));

    render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

    await waitFor(() => expect(screen.getByLabelText("Default standup channel")).toHaveValue("genesis-standups"));
  });

  it("does not render when open is false", () => {
    const { container } = render(<AccountSettingsModal open={false} onClose={mockOnClose} />);
    expect(container).toBeEmptyDOMElement();
  });

  describe("timezone field", () => {
    it("offers a Timezone field alongside the other profile fields", async () => {
      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

      await waitFor(() => expect(screen.getByLabelText("Timezone")).toBeInTheDocument());
    });

    it("preselects the saved timezone when the account already has one", async () => {
      vi.mocked(me).mockResolvedValue(userResponse({ timezone: "Europe/London" }));

      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

      await waitFor(() => expect(screen.getByLabelText("Timezone")).toHaveValue("Europe/London"));
    });

    it("falls back to the browser-detected timezone when the account has none", async () => {
      const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;

      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

      await waitFor(() => expect(screen.getByLabelText("Timezone")).toHaveValue(detected));
    });

    it("saves the chosen timezone when Save changes is clicked", async () => {
      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);
      await waitFor(() => expect(screen.getByLabelText("Timezone")).toBeInTheDocument());

      await userEvent.selectOptions(screen.getByLabelText("Timezone"), "Asia/Karachi");
      await userEvent.click(screen.getByRole("button", { name: /Save changes/i }));

      await waitFor(() => expect(setTimezone).toHaveBeenCalledWith("Asia/Karachi"));
    });

    it("closes the modal once the timezone has saved", async () => {
      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);
      await waitFor(() => expect(screen.getByLabelText("Timezone")).toBeInTheDocument());

      await userEvent.click(screen.getByRole("button", { name: /Save changes/i }));

      await waitFor(() => expect(mockOnClose).toHaveBeenCalled());
    });

    it("does not save when Cancel is clicked", async () => {
      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);
      await waitFor(() => expect(screen.getByLabelText("Timezone")).toBeInTheDocument());

      await userEvent.click(screen.getByRole("button", { name: /Cancel/i }));

      expect(setTimezone).not.toHaveBeenCalled();
      expect(mockOnClose).toHaveBeenCalled();
    });

    it("keeps the modal open and reports the failure when saving fails", async () => {
      vi.mocked(setTimezone).mockRejectedValue(new Error("network down"));

      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);
      await waitFor(() => expect(screen.getByLabelText("Timezone")).toBeInTheDocument());

      await userEvent.click(screen.getByRole("button", { name: /Save changes/i }));

      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
      expect(mockOnClose).not.toHaveBeenCalled();
    });
  });
});
