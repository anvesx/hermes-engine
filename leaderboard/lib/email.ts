import nodemailer from "nodemailer";

/** Sends the sign-in code over SMTP (Gmail by default, with an app password). Without SMTP_PASS (local dev) it logs the code. */
export async function sendCode(email: string, code: string) {
  const user = process.env.SMTP_USER;
  const pass = process.env.SMTP_PASS;
  if (!user || !pass) {
    if (process.env.NODE_ENV === "production") throw new Error("SMTP_USER / SMTP_PASS are not set");
    console.log(`[dev] sign-in code for ${email}: ${code}`);
    return;
  }
  const port = Number(process.env.SMTP_PORT || 465);
  const transport = nodemailer.createTransport({
    host: process.env.SMTP_HOST || "smtp.gmail.com",
    port,
    secure: port === 465,
    auth: { user, pass },
  });
  await transport.sendMail({
    from: process.env.EMAIL_FROM || `Token Metrics <${user}>`,
    to: email,
    subject: `Your token-metrics code: ${code}`,
    text: `Your sign-in code is ${code}. It expires in 10 minutes.\n\nIf you didn't ask for it, ignore this email.`,
  });
}
