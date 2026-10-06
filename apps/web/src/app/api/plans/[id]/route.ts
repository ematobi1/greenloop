import { serverDeps } from "@/server/deps";
import { discardPlan } from "@/server/handlers";

export async function DELETE(request: Request, context: RouteContext<"/api/plans/[id]">) {
  return discardPlan(request, (await context.params).id, serverDeps());
}
