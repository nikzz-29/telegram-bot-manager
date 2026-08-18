import { describe, expect, it } from "vitest";
import { websiteTokenFromHash } from "./SiteApp";

describe("website login link", () => {
  it("reads the one-time token from the URL fragment", () => {
    expect(websiteTokenFromHash("#token=abc-123_%2Fsafe")).toBe("abc-123_/safe");
  });

  it("does not treat unrelated fragments as credentials", () => {
    expect(websiteTokenFromHash("#section=profile")).toBeNull();
    expect(websiteTokenFromHash("")).toBeNull();
  });
});
