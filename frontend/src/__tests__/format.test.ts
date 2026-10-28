import { afterEach, describe, expect, it, vi } from "vitest";
import { formatDateTime, formatMoney, formatPercent, formatRelative } from "@/lib/format";

afterEach(() => vi.useRealTimers());

describe("format helpers", () => {
  it("formats money in USD", () => {
    expect(formatMoney(15)).toContain("15");
    expect(formatMoney(15)).toContain("$");
  });

  it("formats a ratio as a percentage with one decimal", () => {
    expect(formatPercent(0.104)).toBe("10.4%");
  });

  it("shows a dash for missing or invalid dates", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("not-a-date")).toBe("—");
    expect(formatRelative(undefined)).toBe("—");
  });

  it("describes future and past times relative to now", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-28T10:00:00Z"));
    expect(formatRelative("2026-10-28T10:28:00Z")).toBe("in 28 min");
    expect(formatRelative("2026-10-28T08:00:00Z")).toBe("2 h ago");
  });
});
