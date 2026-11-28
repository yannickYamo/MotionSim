// A figure keeps its unit on its line: "4.95 W" never breaks between the number and the W.
import { describe, expect, it } from "vitest";
import { tied } from "../src/format";

describe("a figure tied to its unit", () => {
  it("joins a number to the unit after it with a space that does not break", () => {
    expect(tied("16.6 W conducting, 4.95 W switching")).toBe("16.6 W conducting, 4.95 W switching");
    expect(tied("107 K under 175 °C")).toBe("107 K under 175 °C");
    expect(tied("2.41 %")).toBe("2.41 %");
  });
  it("leaves words that follow no number as they are", () => {
    expect(tied("limit: the motor's current limit")).toBe("limit: the motor's current limit");
  });
});
