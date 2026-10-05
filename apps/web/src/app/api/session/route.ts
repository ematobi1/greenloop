import { serverDeps } from "@/server/deps";
import { sessionStatus, signIn, signOut } from "@/server/handlers";

export function GET(request: Request) {
  return sessionStatus(request);
}

export function POST(request: Request) {
  return signIn(request, serverDeps());
}

export function DELETE(request: Request) {
  return signOut(request, serverDeps());
}
