import { useState } from "react";
import { AuthError, authApi } from "../api";
import { Icon } from "./icons";

/** Login gate shown when the server requires a password and we have no token. */
export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.login(password);
      onSuccess();
    } catch (err) {
      setError(
        err instanceof AuthError
          ? "Incorrect password."
          : "Couldn't reach the server. Is it running?",
      );
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "1.5rem",
      }}
    >
      <form className="card" onSubmit={submit} style={{ width: "min(360px, 100%)" }}>
        <div className="brand" style={{ padding: 0, marginBottom: "1rem" }}>
          <div className="brand-mark">
            <Icon name="load" size={18} />
          </div>
          <div>
            <b>Waypoint</b>
            <span>Sign in to continue</span>
          </div>
        </div>

        <label htmlFor="pw" style={{ display: "block", fontSize: 13, marginBottom: 6 }}>
          Password
        </label>
        <input
          id="pw"
          type="password"
          autoFocus
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "10px 12px",
            border: "1px solid var(--border, #d5dae2)",
            borderRadius: 8,
            fontSize: 15,
            marginBottom: 12,
          }}
        />

        {error && (
          <div style={{ color: "#c0392b", fontSize: 13, marginBottom: 12 }} role="alert">
            {error}
          </div>
        )}

        <button className="btn primary" type="submit" disabled={busy || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
