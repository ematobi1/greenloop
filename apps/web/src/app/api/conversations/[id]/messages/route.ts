import { serverDeps } from "@/server/deps";
import { listMessages, sendMessage } from "@/server/handlers";

export async function GET(request: Request, context: RouteContext<"/api/conversations/[id]/messages">) {
  return listMessages(request, (await context.params).id, serverDeps());
}

export async function POST(request: Request, context: RouteContext<"/api/conversations/[id]/messages">) {
  return sendMessage(request, (await context.params).id, serverDeps());
}
