import { serverDeps } from "@/server/deps";
import { listMemory } from "@/server/handlers";

export function GET(request: Request) {
  return listMemory(request, serverDeps());
}
