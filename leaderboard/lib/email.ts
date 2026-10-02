/** Sends the sign-in code through Resend's HTTP API. Without RESEND_API_KEY (local dev) it logs the code. */
export async function sendCode(email: string, code: string) {
  const key = process.env.RESEND_API_KEY;
  if (!key) {
    if (process.env.NODE_ENV === "production") throw new Error("RESEND_API_KEY is not set");
    console.log(`[dev] sign-in code for ${email}: ${code}`);
    return;
  }
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: process.env.EMAIL_FROM || "Token Metrics <leaderboard@devxlabs.ai>",
      to: [email],
      subject: `Your token-metrics code: ${code}`,
      text: `Your sign-in code is ${code}. It expires in 10 minutes.\n\nIf you didn't ask for it, ignore this email.`,
    }),
  });
  if (!r.ok) throw new Error(`Resend returned ${r.status}: ${await r.text()}`);
}
