import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AccountSettingsModal } from "../AccountSettingsModal";
import { AUTH_STRINGS } from "@/constants/authMessages";
import { useSession } from "@/context/SessionContext";
import { useTheme } from "@/context/ThemeContext";
import { useToast } from "@/context/ToastContext";
import { me } from "@/repositories/api/auth";

vi.mock("@/context/SessionContext", () => ({
  useSession: vi.fn(),
}));

vi.mock("@/context/ThemeContext", () => ({
  useTheme: vi.fn(),
}));

vi.mock("@/context/ToastContext", () => ({
  useToast: vi.fn(),
}));

vi.mock("@/repositories/api/auth", () => ({
  me: vi.fn(),
}));

describe("AccountSettingsModal", () => {
  const mockLogout = vi.fn();
  const mockLogoutAll = vi.fn();
  const mockSetLight = vi.fn();
  const mockSetDark = vi.fn();
  const mockOnClose = vi.fn();

  const mockToastError = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useSession).mockReturnValue({ logout: mockLogout, logoutAll: mockLogoutAll } as unknown as ReturnType<typeof useSession>);
    vi.mocked(useTheme).mockReturnValue({ theme: "light", setLight: mockSetLight, setDark: mockSetDark });
    vi.mocked(useToast).mockReturnValue({ error: mockToastError, success: vi.fn(), info: vi.fn() });
    vi.mocked(me).mockResolvedValue({
      id: 1,
      email: "test@example.com",
      name: "Test User",
      default_channel: null,
      created_at: "2026-01-01T00:00:00Z",
    });
  });

  it("renders profile fields and populates from mocked GET /auth/me", async () => {
    render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

    await waitFor(() => {
      expect(screen.getByDisplayValue("Test User")).toBeInTheDocument();
      expect(screen.getByDisplayValue("test@example.com")).toBeInTheDocument();
    });

    expect(screen.getByText(AUTH_STRINGS.DISPLAY_NAME_LABEL)).toBeInTheDocument();
    expect(screen.getByText(AUTH_STRINGS.WORK_EMAIL_LABEL)).toBeInTheDocument();
  });

  it("allows form fields to be editable", async () => {
    render(<AccountSettingsModal open={true} onClose={mockOnClose} />);
    
    await waitFor(() => {
      expect(screen.getByDisplayValue("Test User")).toBeInTheDocument();
    });
    
    const nameInput = screen.getByDisplayValue("Test User");
    
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "New Name");
    expect(nameInput).toHaveValue("New Name");
  });
  
  it("does not render when open is false", () => {
    const { container } = render(<AccountSettingsModal open={false} onClose={mockOnClose} />);
    expect(container).toBeEmptyDOMElement();
  });

  describe("sign out of all devices", () => {
    it("calls logoutAll after the user confirms", async () => {
      mockLogoutAll.mockResolvedValue(undefined);
      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

      await userEvent.click(screen.getByText(AUTH_STRINGS.SIGN_OUT_ALL_BTN));
      await userEvent.click(screen.getByText(AUTH_STRINGS.SIGN_OUT_ALL_CONFIRM));

      await waitFor(() => expect(mockLogoutAll).toHaveBeenCalledTimes(1));
    });

    it("does not call logoutAll if the user declines the confirmation", async () => {
      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

      await userEvent.click(screen.getByText(AUTH_STRINGS.SIGN_OUT_ALL_BTN));
      await userEvent.click(screen.getByText(AUTH_STRINGS.CANCEL_BTN));

      expect(mockLogoutAll).not.toHaveBeenCalled();
      expect(screen.getByText(AUTH_STRINGS.SIGN_OUT_ALL_BTN)).toBeInTheDocument();
    });

    it("shows an error toast and re-enables the button if logoutAll fails", async () => {
      mockLogoutAll.mockRejectedValue(new Error("network error"));
      render(<AccountSettingsModal open={true} onClose={mockOnClose} />);

      await userEvent.click(screen.getByText(AUTH_STRINGS.SIGN_OUT_ALL_BTN));
      await userEvent.click(screen.getByText(AUTH_STRINGS.SIGN_OUT_ALL_CONFIRM));

      await waitFor(() => expect(mockToastError).toHaveBeenCalledTimes(1));
      expect(screen.getByText(AUTH_STRINGS.SIGN_OUT_ALL_BTN)).not.toBeDisabled();
    });
  });
});
