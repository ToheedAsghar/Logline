import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AccountSettingsModal } from "../AccountSettingsModal";
import { useSession } from "@/context/SessionContext";
import { useTheme } from "@/context/ThemeContext";
import { me } from "@/repositories/api/auth";

vi.mock("@/context/SessionContext", () => ({
  useSession: vi.fn(),
}));

vi.mock("@/context/ThemeContext", () => ({
  useTheme: vi.fn(),
}));

vi.mock("@/repositories/api/auth", () => ({
  me: vi.fn(),
}));

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
});
