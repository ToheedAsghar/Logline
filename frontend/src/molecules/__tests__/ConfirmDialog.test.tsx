import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ConfirmDialog } from "../ConfirmDialog";

describe("ConfirmDialog", () => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when closed", () => {
    render(<ConfirmDialog open={false} title="Discard" message="Really?" onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders the title, message, and themed action buttons", () => {
    render(<ConfirmDialog open title="Discard reconciliation draft" message="Really discard?" onConfirm={onConfirm} onCancel={onCancel} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveTextContent(/Discard reconciliation draft/i);
    expect(dialog).toHaveTextContent(/Really discard\?/i);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
  });

  it("runs onConfirm when the confirm button is clicked", () => {
    render(<ConfirmDialog open title="Discard" message="Really?" confirmLabel="Discard now" onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "Discard now" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("runs onCancel (not onConfirm) on Cancel, backdrop click, Escape, and the ✕ button", () => {
    const { unmount } = render(<ConfirmDialog open title="Discard" message="Really?" onConfirm={onConfirm} onCancel={onCancel} />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onCancel).toHaveBeenCalledTimes(3);

    fireEvent.click(document.querySelector(".fixed.inset-0") as HTMLElement);
    expect(onCancel).toHaveBeenCalledTimes(4);
    unmount();
  });

  it("does not react to Escape when closed", () => {
    render(<ConfirmDialog open={false} title="Discard" message="Really?" onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog on open and returns it to the trigger on close", () => {
    const { rerender } = render(
      <div>
        <button type="button">trigger</button>
        <ConfirmDialog open={false} title="Discard" message="Really?" onConfirm={onConfirm} onCancel={onCancel} />
      </div>
    );

    const trigger = screen.getByRole("button", { name: "trigger" });
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    rerender(
      <div>
        <button type="button">trigger</button>
        <ConfirmDialog open title="Discard" message="Really?" onConfirm={onConfirm} onCancel={onCancel} />
      </div>
    );

    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();

    rerender(
      <div>
        <button type="button">trigger</button>
        <ConfirmDialog open={false} title="Discard" message="Really?" onConfirm={onConfirm} onCancel={onCancel} />
      </div>
    );

    expect(trigger).toHaveFocus();
  });

  it("traps Tab and Shift+Tab within the dialog's focusable elements", () => {
    render(<ConfirmDialog open title="Discard" message="Really?" onConfirm={onConfirm} onCancel={onCancel} />);

    const closeButton = screen.getByRole("button", { name: "Close" });
    const confirmButton = screen.getByRole("button", { name: "Confirm" });

    // jsdom does not move focus on native Tab, so only the wrap-around the
    // handler itself intercepts is testable: Shift+Tab on the first element
    // wraps to the last, and Tab on the last wraps to the first.
    closeButton.focus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(confirmButton).toHaveFocus();

    confirmButton.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(closeButton).toHaveFocus();
  });

  it("keeps focus trapped when working, with only the close button still focusable", () => {
    render(
      <ConfirmDialog open title="Discard" message="Really?" working workingLabel="Discarding…" onConfirm={onConfirm} onCancel={onCancel} />
    );

    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    const closeButton = screen.getByRole("button", { name: "Close" });

    expect(closeButton).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(closeButton).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(closeButton).toHaveFocus();
  });
});
