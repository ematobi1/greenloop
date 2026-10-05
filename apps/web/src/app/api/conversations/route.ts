import { serverDeps } from "@/server/deps";
import { createConversation, listConversations } from "@/server/handlers";

export function GET(request: Request) {
  return listConversations(request, serverDeps());
}

export function POST(request: Request) {
  return createConversation(request, serverDeps());
}
