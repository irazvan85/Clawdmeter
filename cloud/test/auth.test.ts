import type { Account, Profile, Session } from "next-auth";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authOptions, isOwner } from "@/lib/auth";

const signIn = authOptions.callbacks!.signIn!;
const gh = (id: number | string) => ({ id, login: "someone" }) as unknown as Profile;
const github = { provider: "github" } as Account;

describe("sign-in allowlist", () => {
  beforeEach(() => vi.stubEnv("ALLOWED_GITHUB_ID", "1234"));

  it("admits only the configured numeric GitHub id", async () => {
    expect(await signIn({ account: github, profile: gh(1234) } as never)).toBe(true);
    expect(await signIn({ account: github, profile: gh(9999) } as never)).toBe(false);
  });

  it("denies everyone when ALLOWED_GITHUB_ID is unset", async () => {
    vi.stubEnv("ALLOWED_GITHUB_ID", "");
    expect(await signIn({ account: github, profile: gh(1234) } as never)).toBe(false);
  });

  it("isOwner re-checks the id on every request", () => {
    expect(isOwner({ gh: "1234" } as unknown as Session)).toBe(true);
    expect(isOwner({ gh: "9999" } as unknown as Session)).toBe(false);
    expect(isOwner({} as Session)).toBe(false);
    expect(isOwner(null)).toBe(false);
  });
});
