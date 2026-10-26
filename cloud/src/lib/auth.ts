import type { NextAuthOptions, Session } from "next-auth";
import { getServerSession } from "next-auth";
import GithubProvider from "next-auth/providers/github";

// Sign-in is GitHub OAuth, allowed for exactly one account: the numeric
// GitHub user id in ALLOWED_GITHUB_ID. A login name can be renamed and later
// re-registered by someone else; the numeric id can't. Anyone else gets
// refused at sign-in, and isOwner() re-checks on every request anyway.

type OwnerSession = Session & { gh?: string };

export const authOptions: NextAuthOptions = {
  providers: [
    GithubProvider({
      clientId: process.env.GITHUB_ID ?? "",
      clientSecret: process.env.GITHUB_SECRET ?? "",
    }),
  ],
  session: { strategy: "jwt", maxAge: 7 * 24 * 3600 },
  callbacks: {
    async signIn({ account, profile }) {
      const allowed = process.env.ALLOWED_GITHUB_ID;
      const id = (profile as { id?: number | string } | undefined)?.id;
      return !!allowed && account?.provider === "github" && String(id) === allowed;
    },
    async jwt({ token, profile }) {
      const id = (profile as { id?: number | string } | undefined)?.id;
      if (id != null) token.gh = String(id);
      return token;
    },
    async session({ session, token }) {
      (session as OwnerSession).gh = typeof token.gh === "string" ? token.gh : undefined;
      return session;
    },
  },
};

export function isOwner(session: Session | null): boolean {
  const allowed = process.env.ALLOWED_GITHUB_ID;
  return !!allowed && !!session && (session as OwnerSession).gh === allowed;
}

export async function ownerSession(): Promise<boolean> {
  return isOwner(await getServerSession(authOptions));
}
