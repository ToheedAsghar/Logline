import { render, screen, fireEvent, act } from "@testing-library/react";

import { describe, it, expect, vi, beforeEach } from "vitest";
import { TrackerDeviceEnrollment } from "../TrackerDeviceEnrollment";
import { useEnrollTrackerDevice } from "@/repositories/hooks";

vi.mock("@/repositories/hooks", () => ({
  useEnrollTrackerDevice: vi.fn(),
}));

describe("TrackerDeviceEnrollment", () => {
  const mockMutate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useEnrollTrackerDevice).mockReturnValue({
      mutate: mockMutate,
      isPending: false,
    } as unknown as ReturnType<typeof useEnrollTrackerDevice>);

  });

  it("renders 'Connect this device' when deviceCount is 0", () => {
    render(<TrackerDeviceEnrollment deviceCount={0} />);
    expect(screen.getByRole("button", { name: "Connect this device" })).toBeInTheDocument();
  });

  it("renders 'Connect another device' when deviceCount is greater than 0", () => {
    render(<TrackerDeviceEnrollment deviceCount={1} />);
    expect(screen.getByRole("button", { name: "Connect another device" })).toBeInTheDocument();
  });

  it("displays token on successful enrollment with copy and done actions", async () => {
    mockMutate.mockImplementation((_name, { onSuccess }) => {
      onSuccess({
        device_id: "123e4567-e89b-12d3-a456-426614174000",
        name: "My Mac",
        token: "logline_tok_secret12345",
        created_at: new Date().toISOString(),
      });
    });

    // Mock clipboard API
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    const { rerender } = render(<TrackerDeviceEnrollment deviceCount={0} />);

    // Click enrollment button
    fireEvent.click(screen.getByRole("button", { name: "Connect this device" }));

    expect(mockMutate).toHaveBeenCalledWith(undefined, expect.any(Object));

    // Verify token displayed clearly
    expect(screen.getByTestId("device-token-display")).toHaveTextContent("logline_tok_secret12345");
    expect(screen.getByText(/Copy this token now/i)).toBeInTheDocument();

    // Verify copy button works
    const copyBtn = screen.getByRole("button", { name: "Copy token" });
    await act(async () => {
      fireEvent.click(copyBtn);
    });
    expect(writeTextMock).toHaveBeenCalledWith("logline_tok_secret12345");


    // Click 'Done' to dismiss token
    const doneBtn = screen.getByRole("button", { name: "Done" });
    fireEvent.click(doneBtn);

    // Verify token is no longer displayed or accessible in the DOM
    expect(screen.queryByTestId("device-token-display")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect this device" })).toBeInTheDocument();

    // Rerendering component simulates a page refresh / component remount
    rerender(<TrackerDeviceEnrollment deviceCount={1} />);
    expect(screen.queryByTestId("device-token-display")).not.toBeInTheDocument();
  });

  it("renders error state when enrollment fails", () => {
    mockMutate.mockImplementation((_name, { onError }) => {
      onError(new Error("Network failure"));
    });

    render(<TrackerDeviceEnrollment deviceCount={0} />);

    fireEvent.click(screen.getByRole("button", { name: "Connect this device" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Network failure");

    // Dismiss error
    fireEvent.click(screen.getByRole("button", { name: "Dismiss error" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
