import { describe, expect, it } from "vitest";
import { formatBytes, formatCell, formatNumber } from "../lib/format";
import { parseSseBlocks } from "../api/client";

describe("formatting", () => {
  it("formats numbers and midnight timestamps", () => {
    expect(formatCell("2025-03-01 00:00:00")).toBe("2025-03-01");
    expect(formatCell(null)).toBe("");
    expect(formatNumber(1234567, "compact")).toMatch(/1\.2\s?M/);
    expect(formatBytes(2048)).toBe("2 KB");
  });
});

describe("SSE parsing", () => {
  it("parses event blocks and ignores comments", () => {
    const text = ': stream-open\n\nevent: step\ndata: {"type":"step","id":"s1"}\n\nevent: done\ndata: {"type":"done","message_id":"m"}\n\n';
    expect(parseSseBlocks(text).map((e) => e.type)).toEqual(["step", "done"]);
  });
});
