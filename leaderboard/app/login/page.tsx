import { googleEnabled } from "@/lib/google";
import LoginForm from "./form";

export const dynamic = "force-dynamic";

export default function Login() {
  return <LoginForm google={googleEnabled()} />;
}
