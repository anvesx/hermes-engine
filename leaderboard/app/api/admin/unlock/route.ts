import { currentUser, isAdmin } from "@/lib/auth";
import { passwordOk, unlockAdmin } from "@/lib/admin";

export async function POST(req: Request) {
  const user = await currentUser();
  if (!isAdmin(user)) return new Response("not found", { status: 404 });
  if (!process.env.ADMIN_PASSWORD) console.error("ADMIN_PASSWORD is not set; /admin stays locked");
  const form = await req.formData();
  if (!passwordOk(form.get("password"))) {
    await new Promise((r) => setTimeout(r, 800)); // slow down guessing
    return Response.redirect(new URL("/admin?denied=1", req.url), 303);
  }
  await unlockAdmin(String(user!.id));
  return Response.redirect(new URL("/admin", req.url), 303);
}
