import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Chart } from "./Chart";
import type { Point } from "../types";

const series: Point[] = [
  { date: "2026-08-17", messages: 4, active_users: 3, joins: 1, leaves: 0, moderation_actions: 1 },
  { date: "2026-08-18", messages: 9, active_users: 5, joins: 2, leaves: 1, moderation_actions: 0 },
];

describe("Chart", () => {
  it("keeps one svg mounted while data changes", () => {
    const view = render(<Chart series={series} metric="messages" total={13} locale="en" />);
    const svg = screen.getByRole("img");
    view.rerender(<Chart series={series.map((point) => ({ ...point, messages: point.messages * 2 }))} metric="messages" total={26} locale="en" />);
    expect(screen.getByRole("img")).toBe(svg);
    expect(screen.getByText("26")).toBeInTheDocument();
  });

  it("shows exact localized point data for keyboard focus", () => {
    render(<Chart series={series} metric="messages" total={13} locale="en" label="Messages" />);
    const points = screen.getAllByRole("button", { name: /2026|Aug/ });
    fireEvent.focus(points[0]);
    expect(screen.getByRole("status")).toHaveTextContent("Messages");
    expect(screen.getByRole("status")).toHaveTextContent("4");
    fireEvent.blur(points[0]);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders axis dates outside the non-uniformly scaled svg", () => {
    const view = render(<Chart series={series} metric="messages" total={13} locale="en" />);
    const axis = view.container.querySelector(".chart-axis-labels");

    expect(axis).toHaveTextContent("2026-08-17");
    expect(axis).toHaveTextContent("2026-08-18");
    expect(screen.getByRole("img").querySelector("text")).toBeNull();
  });
});
