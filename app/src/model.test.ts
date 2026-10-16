import { describe, expect, it } from "vitest";
import { fmtDate, makeScale, verdict } from "./model";
import type { Bundle } from "./types";

const bundle = (start: string, end: string) => ({ span: { start, end } }) as Bundle;

describe("scale", () => {
  it("pads to whole months and places dates proportionally", () => {
    const s = makeScale(bundle("2024-01-18", "2025-03-18"));
    expect(s.start).toBe("2024-01-01");
    expect(s.end).toBe("2025-04-01");
    expect(s.monthBuckets).toHaveLength(15);
    expect(s.x("2024-01-01")).toBe(0);
    expect(s.x("2025-04-01")).toBe(1);
    expect(s.ticks[0].label).toBe("Jan 24");
  });
  it("thins ticks on long histories", () => {
    const s = makeScale(bundle("2015-01-01", "2025-01-01"));
    expect(s.ticks.length).toBeLessThan(15);
  });
});

describe("labels", () => {
  it("formats by precision", () => {
    expect(fmtDate("2024-04-01", "month")).toBe("Apr 2024");
    expect(fmtDate("2025-01-22")).toBe("22 Jan 2025");
    expect(fmtDate(null)).toBe("Undated");
  });
  it("describes timing without claiming cause", () => {
    const w = (n: number) => ({ start: "", end: "", episodes: n, worst_episodes: 0, per_month: n });
    expect(verdict({ before: w(2), after: w(0.5) } as any).text).toBe("Fewer episodes after");
    expect(verdict({ before: w(1), after: null } as any).text).toBe("Too soon to tell");
  });
});
