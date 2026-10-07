import { serverDeps } from "@/server/deps";
import { deleteMemory } from "@/server/handlers";

export async function DELETE(request: Request, context: RouteContext<"/api/memory/[id]">) {
  return deleteMemory(request, (await context.params).id, serverDeps());
}
