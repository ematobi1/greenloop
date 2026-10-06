import { cookies } from "next/headers";

import MemoryApp from "@/components/memory/MemoryApp";
import { SESSION_COOKIE } from "@/server/session";

export default async function Page() {
  const signedIn = (await cookies()).has(SESSION_COOKIE);
  return <MemoryApp initiallySignedIn={signedIn} />;
}
