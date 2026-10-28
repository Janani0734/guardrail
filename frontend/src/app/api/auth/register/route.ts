import { NextRequest } from "next/server";
import { authResponse, backendJson } from "@/lib/server/backend";

export async function POST(req: NextRequest) {
  const body = await req.text();
  const result = await backendJson("/v1/auth/register", { method: "POST", headers: { "content-type": "application/json" }, body });
  return authResponse(result, 201);
}
