import { serverDeps } from "@/server/deps";
import { memoryHistory } from "@/server/handlers";

export async function GET(request: Request, context: RouteContext<"/api/memory/[id]/history">) {
  return memoryHistory(request, (await context.params).id, serverDeps());
}
