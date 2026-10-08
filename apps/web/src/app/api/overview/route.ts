import { serverDeps } from "@/server/deps";
import { overview } from "@/server/handlers";

export function GET(request: Request) {
  return overview(request, serverDeps());
}
