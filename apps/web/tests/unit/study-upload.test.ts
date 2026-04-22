import { describe, expect, it } from "vitest";
import { STUDY_UPLOAD_ACCEPT } from "@/lib/study-upload";

describe("study upload accept list", () => {
  it("leaves the picker unrestricted so any file can enter the study pipeline", () => {
    expect(STUDY_UPLOAD_ACCEPT).toBe("");
  });
});
