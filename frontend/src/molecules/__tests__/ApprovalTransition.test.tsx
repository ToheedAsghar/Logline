import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalTransition } from "../ApprovalTransition";

const approveMutate = vi.fn();

vi.mock("@/repositories/hooks", () => ({
  useApproveEntry: () => ({ mutate: approveMutate, isPending: false, isError: false }),
}));

describe("ApprovalTransition", () => {
  it("renders discarded entries as inert instead of offering approval", () => {
    render(<ApprovalTransition entry={{ id: 42, status: "discarded" }} />);

    expect(screen.getByText("Discarded")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(approveMutate).not.toHaveBeenCalled();
  });
});
