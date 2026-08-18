import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Sidebar } from "./SiteApp";

describe("desktop sidebar navigation", () => {
  it("renders semantic SVG markers for every section without changing accessible labels", () => {
    render(
      <Sidebar
        section="overview"
        setSection={vi.fn()}
        profile={{
          user: {
            tg_user_id: 42,
            username: "dmitry",
            first_name: "Dmitry",
            last_name: null,
            language_code: "ru",
            is_superadmin: false,
            is_premium: false,
            has_photo: false,
            photo_url: null,
          },
          display_name: "Dmitry",
          first_seen_at: null,
          chats_total: 0,
          chats_owned: 0,
          chats_admin: 0,
          paid_chats: 0,
          total_members: 0,
        }}
        theme="light"
        toggleTheme={vi.fn()}
        logout={vi.fn()}
        t={(key) => key}
      />,
    );

    const buttons = screen.getAllByRole("button");
    const navigationButtons = buttons.slice(0, 5);
    expect(navigationButtons).toHaveLength(5);
    expect(navigationButtons.map((button) => button.textContent)).toEqual([
      "nav.overview",
      "nav.activity",
      "nav.chats",
      "nav.plans",
      "nav.profile",
    ]);
    navigationButtons.forEach((button) => {
      expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    });
    expect(screen.queryByText("01")).not.toBeInTheDocument();
  });
});
