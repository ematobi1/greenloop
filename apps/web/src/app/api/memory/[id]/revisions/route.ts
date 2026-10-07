import { serverDeps } from "@/server/deps";
import { reviseMemory } from "@/server/handlers";

export async function POST(request: Request, context: RouteContext<"/api/memory/[id]/revisions">) {
  return reviseMemory(request, (await context.params).id, serverDeps());
}
