import { fromLocalInput, humanize, localInputValue, money, pct, relative, setFleetLocale, time } from "@/lib/format";

describe("fleet-time formatting", () => {
  beforeEach(() => setFleetLocale("Asia/Kolkata", "INR"));

  it("renders times in the fleet timezone", () => {
    expect(time("2026-10-03T00:30:00Z")).toBe("06:00");
  });

  it("round-trips datetime-local values through the fleet timezone", () => {
    const iso = "2026-10-03T18:45:00.000Z";
    const local = localInputValue(new Date(iso));
    expect(local).toBe("2026-10-04T00:15");
    expect(fromLocalInput(local)).toBe(iso);
  });

  it("formats money, percentages and labels", () => {
    expect(money(1234.5)).toContain("1,235");
    expect(pct(72.4)).toBe("72%");
    expect(pct(null)).toBe("—");
    expect(humanize("needs_charge")).toBe("Needs charge");
  });

  it("describes relative times", () => {
    const now = Date.parse("2026-10-03T10:00:00Z");
    expect(relative("2026-10-03T10:45:00Z", now)).toBe("in 45 min");
    expect(relative("2026-10-03T08:00:00Z", now)).toBe("2 h ago");
  });
});
