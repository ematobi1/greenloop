import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import Shell from "@/components/shell/Shell";
import { SESSION_COOKIE, SESSION_ENDED_COOKIE } from "@/server/session";

// Only checks that the session cookie exists; the API's 401 is the real check, and the
// client sends an expired session back to /sign-in (ADR 0012, ADR 0014).
export default async function HudLayout({ children }: LayoutProps<"/">) {
  const jar = await cookies();
  if (!jar.has(SESSION_COOKIE)) redirect(jar.has(SESSION_ENDED_COOKIE) ? "/sign-in?expired=1" : "/sign-in");
  return <Shell>{children}</Shell>;
}
