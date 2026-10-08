import { serverDeps } from "@/server/deps";
import { currentSession, signIn, signOut } from "@/server/handlers";

export function GET(request: Request) {
  return currentSession(request, serverDeps());
}

export function POST(request: Request) {
  return signIn(request, serverDeps());
}

export function DELETE(request: Request) {
  return signOut(request, serverDeps());
}
