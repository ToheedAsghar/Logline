import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
    
    // Wait for the auth/me call to populate
    await waitFor(() => {
      expect(screen.getByDisplayValue("Test User")).toBeInTheDocument();
      expect(screen.getByDisplayValue("test@example.com")).toBeInTheDocument();
    });
    
    expect(screen.getByText("Display name")).toBeInTheDocument();
    expect(screen.getByText("Work email")).toBeInTheDocument();
  });

  it("calls the theme context correctly when Light/Dark toggles are clicked", async () => {
    render(<AccountSettingsModal open={true} onClose={mockOnClose} />);
    
    // Wait for the auth/me call to populate
    await waitFor(() => {
      expect(screen.getByDisplayValue("Test User")).toBeInTheDocument();
    });
    
    const darkBtn = screen.getByRole("button", { name: /Dark/ });
    const lightBtn = screen.getByRole("button", { name: /Light/ });
    
    fireEvent.click(darkBtn);
    expect(mockSetDark).toHaveBeenCalledTimes(1);
    
    fireEvent.click(lightBtn);
    expect(mockSetLight).toHaveBeenCalledTimes(1);
  });

  it("allows form fields to be editable", async () => {
    render(<AccountSettingsModal open={true} onClose={mockOnClose} />);
    
    await waitFor(() => {
      expect(screen.getByDisplayValue("Test User")).toBeInTheDocument();
    });
    
    const nameInput = screen.getByDisplayValue("Test User");
    // Actually the placeholder @handle is for the handle field, role has no placeholder but label is Role
    // Let's find inputs by their associated label or by value if populated
    
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "New Name");
    expect(nameInput).toHaveValue("New Name");
  });
  
  it("does not render when open is false", () => {
    const { container } = render(<AccountSettingsModal open={false} onClose={mockOnClose} />);
    expect(container).toBeEmptyDOMElement();
  });
});
