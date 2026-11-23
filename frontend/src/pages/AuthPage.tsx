import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";

type Mode = "signin" | "signup";

export function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "signin") await login(email, password);
      else await register(email, name, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  return (
    <main className="auth">
      <section className="auth-intro" aria-hidden="true">
        <div className="brand brand-large">
          <Mark /> Quarry
        </div>
        <p className="auth-lede">Upload a spreadsheet export. Ask what happened. Get the number, the chart and the query behind it.</p>
        <figure className="auth-sample">
          <p className="sample-q">Which region generated the highest revenue?</p>
          <div className="sample-a">
            <p>
              <strong>West</strong>, with 406,131 in revenue, 15% ahead of East.
            </p>
            <div className="sample-bars">
              {[
                ["West", 100],
                ["East", 87],
                ["North", 86],
                ["Central", 73],
                ["South", 71],
              ].map(([label, w]) => (
                <div key={label} className="sample-bar">
                  <span>{label}</span>
                  <i style={{ width: `${w}%` }} />
                </div>
              ))}
            </div>
            <code>SELECT region, sum(revenue) FROM sales GROUP BY region</code>
          </div>
        </figure>
      </section>

      <section className="auth-form-wrap">
        <form className="auth-form" onSubmit={submit} noValidate>
          <h1>{mode === "signin" ? "Sign in" : "Create your account"}</h1>
          {mode === "signup" && (
            <label>
              Full name
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required maxLength={120} />
            </label>
          )}
          <label>
            Work email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              autoFocus
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              required
              minLength={mode === "signup" ? 10 : undefined}
              maxLength={128}
            />
            {mode === "signup" && <span className="hint">At least 10 characters, with a letter and a number.</span>}
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn-primary btn-block" disabled={busy}>
            {busy ? "Please wait" : mode === "signin" ? "Sign in" : "Create account"}
          </button>
          <p className="auth-switch">
            {mode === "signin" ? (
              <>
                New to Quarry?{" "}
                <button type="button" className="link" onClick={() => switchMode("signup")}>
                  Create an account
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button type="button" className="link" onClick={() => switchMode("signin")}>
                  Sign in
                </button>
              </>
            )}
          </p>
        </form>
      </section>
    </main>
  );
}

export function Mark() {
  return (
    <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="currentColor" />
      <path d="M8 22 L13 11 L18 18 L21 14 L25 22 Z" fill="var(--moss-light)" />
    </svg>
  );
}
