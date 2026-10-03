import { lockAdmin } from "@/lib/admin";

export async function POST(req: Request) {
  await lockAdmin();
  return Response.redirect(new URL("/admin", req.url), 303);
}
