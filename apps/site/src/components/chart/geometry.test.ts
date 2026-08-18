import { describe, expect, it } from "vitest";
import { getPointRadii, interpolateGeometry, resampleSeries, toGeometry } from "./geometry";

describe("chart geometry", () => {
  it("normalizes an empty and a single point series without NaN coordinates", () => {
    expect(toGeometry([], "messages")).toEqual([]);
    const one = toGeometry([{ date: "2026-08-18", messages: 4, active_users: 2, joins: 0, leaves: 0, moderation_actions: 0 }], "messages");
    expect(one).toHaveLength(1);
    expect(one[0].x).toBe(50);
    expect(Number.isFinite(one[0].y)).toBe(true);
  });

  it("resamples by normalized time and interpolates endpoints", () => {
    const source = [
      { date: "2026-08-17", messages: 0, active_users: 0, joins: 0, leaves: 0, moderation_actions: 0 },
      { date: "2026-08-18", messages: 10, active_users: 0, joins: 0, leaves: 0, moderation_actions: 0 },
    ];
    const target = resampleSeries(source, "messages", 5);
    expect(target.map((point) => point.value)).toEqual([0, 2.5, 5, 7.5, 10]);
    const start = interpolateGeometry(toGeometry(source, "messages", 5), toGeometry([{ ...source[0], messages: 20 }, { ...source[1], messages: 30 }], "messages", 5), 0);
    const end = interpolateGeometry(start, toGeometry([{ ...source[0], messages: 20 }, { ...source[1], messages: 30 }], "messages", 5), 1);
    expect(start[0].y).not.toBe(end[0].y);
    expect(Number.isFinite(end.at(-1)?.y)).toBe(true);
  });

  it("keeps exact source dates aligned with exact source values", () => {
    const target = resampleSeries([
      { date: "2026-08-16", messages: 2, active_users: 1, joins: 0, leaves: 0, moderation_actions: 0 },
      { date: "2026-08-17", messages: 24, active_users: 1, joins: 0, leaves: 0, moderation_actions: 0 },
    ], "messages", 2);
    expect(target).toEqual([{ date: "2026-08-16", value: 2 }, { date: "2026-08-17", value: 24 }]);
  });

  it("compensates point radii for a non-uniformly scaled svg", () => {
    expect(getPointRadii(2, 800, 250)).toEqual({ rx: 0.71, ry: 2 });
    expect(getPointRadii(2, 400, 352)).toEqual({ rx: 2, ry: 2 });
  });
});
