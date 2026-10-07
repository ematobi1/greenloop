import { serverDeps } from "@/server/deps";
import { draftPlan, listPlans } from "@/server/handlers";

export function GET(request: Request) {
  return listPlans(request, serverDeps());
}

export function POST(request: Request) {
  return draftPlan(request, serverDeps());
}
