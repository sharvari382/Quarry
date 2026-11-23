import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnswerBlock, type TurnView } from "../components/AnswerBlock";
import { DataTable } from "../components/DataTable";

describe("DataTable", () => {
  it("sorts numeric columns when the header is clicked", () => {
    render(<DataTable columns={["region", "rev"]} rows={[["A", 5], ["B", 50], ["C", 10]]} />);
    fireEvent.click(screen.getByRole("button", { name: /rev/ }));
    const cells = screen.getAllByRole("cell").filter((_, i) => i % 2 === 1).map((c) => c.textContent);
    expect(cells).toEqual(["5", "10", "50"]);
  });
});

describe("AnswerBlock", () => {
  const turn: TurnView = {
    key: "t", question: "Top region?", live: false,
    steps: [{ id: "s1", tool: "run_sql", label: "Querying data", input: { sql: "SELECT 1", purpose: "x" }, ok: true, elapsed_ms: 12 }],
    items: [], answer: "**West** leads. <script>alert(1)</script>",
    reasoning: ["Summed revenue by region"], sql: "SELECT region FROM sales", followUps: ["By month?"],
  };

  it("renders markdown without executing raw HTML and wires follow-ups", () => {
    const onFollowUp = vi.fn();
    const { container } = render(<AnswerBlock turn={turn} onFollowUp={onFollowUp} onExportCsv={() => {}} />);
    expect(screen.getByText("West").tagName).toBe("STRONG");
    expect(container.querySelector("script")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "By month?" }));
    expect(onFollowUp).toHaveBeenCalledWith("By month?");
  });

  it("reveals the working on demand", () => {
    render(<AnswerBlock turn={turn} onFollowUp={() => {}} onExportCsv={() => {}} />);
    expect(screen.queryByText("SELECT 1")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Show working/ }));
    expect(screen.getByText("SELECT 1")).toBeInTheDocument();
  });
});
