"use client";
import { useEffect, useState } from "react";

const GOOGLE_ERRORS: Record<string, string> = {
  failed: "Google sign-in didn't complete. Try again, or use an email code below.",
  domain: "Use your devxlabs.ai Google account. Personal Google accounts can't sign in.",
  cancelled: "Google sign-in was cancelled.",
  off: "Google sign-in isn't set up yet. Use an email code below.",
};

export default function LoginForm({ google }: { google: boolean }) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    if (sp.has("expired"))
      setError("That sign-in link expired or was already used. Run /token-metrics:dashboard again, or sign in here.");
    const g = sp.get("google");
    if (g) setError(GOOGLE_ERRORS[g] ?? GOOGLE_ERRORS.failed);
  }, []);

  async function post(path: string, body: object) {
    setBusy(true);
    setError("");
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    setBusy(false);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) setError(data.error || "something went wrong");
    return r.ok;
  }

  return (
    <main style={{ maxWidth: 420 }}>
      <h1>Token Leaderboard</h1>
      <p className="muted">Sign in with your work account to see the company leaderboard.</p>
      {google && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <a href="/api/auth/google" className="button" style={{ display: "block", textAlign: "center" }}>Sign in with Google</a>
          <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>Or get a one-time code by email:</p>
        </div>
      )}
      <div className="panel">
        {!sent ? (
          <form onSubmit={async (e) => { e.preventDefault(); if (await post("/api/auth/start", { email })) setSent(true); }}>
            <div className="row" style={{ flexDirection: "column", alignItems: "stretch" }}>
              <input type="email" required placeholder="you@devxlabs.ai" value={email} onChange={(e) => setEmail(e.target.value)} />
              <button disabled={busy}>Email me a code</button>
            </div>
          </form>
        ) : (
          <form onSubmit={async (e) => {
            e.preventDefault();
            if (await post("/api/auth/verify", { email, code, display_name: name, web: true })) window.location.href = "/";
          }}>
            <div className="row" style={{ flexDirection: "column", alignItems: "stretch" }}>
              <span className="muted">Code sent to {email}</span>
              <input inputMode="numeric" required placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} />
              <input placeholder="Display name (first sign-in only)" value={name} onChange={(e) => setName(e.target.value)} />
              <button disabled={busy}>Sign in</button>
            </div>
          </form>
        )}
        {error && <p style={{ color: "var(--accent)" }}>{error}</p>}
      </div>
      <p className="muted" style={{ marginTop: 24 }}>
        To appear on the board, install the token-metrics plugin and run <code>/token-metrics:dashboard</code> in Claude Code.
      </p>
    </main>
  );
}
