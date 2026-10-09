import { serverDeps } from "@/server/deps";
import { health } from "@/server/handlers";

export function GET(request: Request) {
  return health(request, serverDeps());
}
