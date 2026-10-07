import { serverDeps } from "@/server/deps";
import { rememberMessage } from "@/server/handlers";

export async function POST(
  request: Request,
  context: RouteContext<"/api/conversations/[id]/messages/[messageId]/remember">,
) {
  const { id, messageId } = await context.params;
  return rememberMessage(request, id, messageId, serverDeps());
}
