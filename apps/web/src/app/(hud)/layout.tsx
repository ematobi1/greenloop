import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import Shell from "@/components/shell/Shell";
import { SESSION_COOKIE } from "@/server/session";

// Only checks that the session cookie exists; the API's 401 is the real check, and the
// client sends an expired session back to /sign-in (ADR 0012, ADR 0014).
export default async function HudLayout({ children }: LayoutProps<"/">) {
  if (!(await cookies()).has(SESSION_COOKIE)) redirect("/sign-in");
  return <Shell>{children}</Shell>;
}
