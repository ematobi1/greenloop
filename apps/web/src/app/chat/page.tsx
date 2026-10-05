import { cookies } from "next/headers";

import ChatApp from "@/components/chat/ChatApp";
import { SESSION_COOKIE } from "@/server/session";

// Reads only whether the session cookie exists; the token itself never leaves the server.
export default async function Page() {
  const signedIn = (await cookies()).has(SESSION_COOKIE);
  return <ChatApp initiallySignedIn={signedIn} />;
}
