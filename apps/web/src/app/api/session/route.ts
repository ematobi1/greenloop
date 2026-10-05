import { serverDeps } from "@/server/deps";
import { signIn, signOut } from "@/server/handlers";

export function POST(request: Request) {
  return signIn(request, serverDeps());
}

export function DELETE(request: Request) {
  return signOut(request, serverDeps());
}
