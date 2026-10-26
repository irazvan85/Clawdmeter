import { ownerSession } from "@/lib/auth";
import Dashboard from "./dashboard";

// Session is checked on the server before anything renders: a visitor who
// isn't the owner gets the sign-in prompt and no device data, not even the
// dashboard's markup.

export const dynamic = "force-dynamic";

export default async function Page() {
  if (await ownerSession()) return <Dashboard />;
  return (
    <main className="signin">
      <h1>Clawdmeter</h1>
      <p className="dim">Private dashboard. Sign in with the GitHub account it belongs to.</p>
      <a className="button" href="/api/auth/signin/github">
        Sign in with GitHub
      </a>
    </main>
  );
}
