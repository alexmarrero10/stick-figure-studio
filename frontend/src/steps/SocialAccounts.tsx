import { useEffect, useState } from "react";
import { api } from "../api";
import { CopyButton, ErrorBox, SecretInput } from "../components";

type Login = "youtube" | "meta" | "tiktok";

interface LoginStatus {
  app_id: string;
  app_secret: string | null;
  app_ready: boolean;
  redirect_uri: string;
  account: string;
  instagram?: string;
}

type SocialStatus = Record<Login, LoginStatus> & { platforms: Record<string, boolean> };

const LOGINS: { key: Login; label: string; idLabel: string; secretLabel: string; steps: React.ReactNode }[] = [
  {
    key: "youtube",
    label: "YouTube",
    idLabel: "OAuth client ID",
    secretLabel: "OAuth client secret",
    steps: (
      <ol className="small">
        <li>
          In{" "}
          <a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer">
            Google Cloud Console
          </a>
          , create a project and enable <strong>YouTube Data API v3</strong>.
        </li>
        <li>
          Set up the OAuth consent screen (External) and add yourself as a test user. Then publish it (
          <strong>In production</strong>), or the login expires every 7 days.
        </li>
        <li>
          Create an OAuth client ID of type <strong>Desktop app</strong> and paste its ID and secret here.
        </li>
      </ol>
    ),
  },
  {
    key: "meta",
    label: "Facebook + Instagram",
    idLabel: "Meta app ID",
    secretLabel: "Meta app secret",
    steps: (
      <ol className="small">
        <li>Make your Instagram a professional account (Creator or Business) and link it to your Facebook Page.</li>
        <li>
          At{" "}
          <a href="https://developers.facebook.com/apps" target="_blank" rel="noreferrer">
            developers.facebook.com
          </a>
          , create a Business app and add the <strong>Facebook Login for Business</strong> and{" "}
          <strong>Instagram</strong> products.
        </li>
        <li>Add the redirect URI below under Facebook Login → Settings → Valid OAuth Redirect URIs.</li>
        <li>
          Paste the app ID and secret (App settings → Basic) here. When you connect, pick your Page and your Instagram
          account.
        </li>
      </ol>
    ),
  },
  {
    key: "tiktok",
    label: "TikTok",
    idLabel: "Client key",
    secretLabel: "Client secret",
    steps: (
      <ol className="small">
        <li>
          At{" "}
          <a href="https://developers.tiktok.com/apps" target="_blank" rel="noreferrer">
            developers.tiktok.com
          </a>
          , create an app with <strong>Login Kit</strong> and the <strong>Content Posting API</strong> (Direct Post
          turned on).
        </li>
        <li>Add the redirect URI below, and the scopes user.info.basic and video.publish.</li>
        <li>Paste the client key and secret here.</li>
      </ol>
    ),
  },
];

const EMPTY = { id: "", secret: "" };

export default function SocialAccounts() {
  const [st, setSt] = useState<SocialStatus | null>(null);
  const [form, setForm] = useState<Record<Login, { id: string; secret: string }>>({
    youtube: EMPTY,
    meta: EMPTY,
    tiktok: EMPTY,
  });
  const [msg, setMsg] = useState<Partial<Record<Login, string>>>({});
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .get<SocialStatus>("/api/social")
      .then(setSt)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    // Pick up a login finished in the other tab.
    const on = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  if (!st) return <ErrorBox error={error} />;

  const saveApp = async (login: Login) => {
    setError(null);
    try {
      await api.put("/api/social/app", { login, app_id: form[login].id, app_secret: form[login].secret });
      setForm({ ...form, [login]: EMPTY });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const test = async (login: Login) => {
    setMsg({ ...msg, [login]: "Checking…" });
    try {
      const r = await api.post<{ account: string }>(`/api/social/${login}/test`);
      setMsg({ ...msg, [login]: `Working: ${r.account}` });
    } catch (e) {
      setMsg({ ...msg, [login]: (e as Error).message });
    }
  };

  const disconnect = async (login: Login) => {
    if (!window.confirm("Disconnect this account? You can connect it again later.")) return;
    await api.post(`/api/social/${login}/disconnect`);
    setMsg({ ...msg, [login]: "" });
    load();
  };

  const isConnected = (login: Login) => (login === "meta" ? st.platforms.facebook : st.platforms[login]);

  return (
    <div className="panel">
      <h2>Connected accounts</h2>
      <p className="muted small">
        Used by "Publish short form videos" on a project's Short step. Each app needs a free developer app of your own.
        Its ID and secret are saved to the .env file, and Connect opens that app's own login page in a new tab.
      </p>
      <ErrorBox error={error} onClose={() => setError(null)} />
      {LOGINS.map((l) => {
        const s = st[l.key];
        const on = isConnected(l.key);
        return (
          <details key={l.key} className="account" open={!s.app_ready}>
            <summary>
              <strong>{l.label}</strong>{" "}
              {on ? (
                <span className="good small">
                  Connected: {s.account}
                  {l.key === "meta" && (s.instagram ? ` + Instagram @${s.instagram}` : " (no Instagram linked)")}
                </span>
              ) : (
                <span className="muted small">{s.app_ready ? "Not connected" : "Needs setup"}</span>
              )}
            </summary>
            {l.steps}
            <p className="small">
              Redirect URI: <code>{s.redirect_uri}</code> <CopyButton text={s.redirect_uri} />
            </p>
            <div className="grid2">
              <label>
                <span>
                  {l.idLabel} <span className="muted">{s.app_id ? `(current: ${s.app_id})` : "(not set)"}</span>
                </span>
                <input
                  value={form[l.key].id}
                  onChange={(e) => setForm({ ...form, [l.key]: { ...form[l.key], id: e.target.value } })}
                />
              </label>
              <label>
                <span>
                  {l.secretLabel} <span className="muted">{s.app_secret ? `(current: ${s.app_secret})` : "(not set)"}</span>
                </span>
                <SecretInput
                  value={form[l.key].secret}
                  onChange={(v) => setForm({ ...form, [l.key]: { ...form[l.key], secret: v } })}
                />
              </label>
            </div>
            <div className="row">
              <button
                className="secondary small"
                onClick={() => saveApp(l.key)}
                disabled={!form[l.key].id && !form[l.key].secret}
              >
                Save
              </button>
              {s.app_ready ? (
                <a className="button small" href={`/api/social/${l.key}/connect`} target="_blank" rel="noreferrer">
                  {on ? "Reconnect" : "Connect"}
                </a>
              ) : (
                <button className="small" disabled>
                  Connect
                </button>
              )}
              {on && (
                <>
                  <button className="secondary small" onClick={() => test(l.key)}>
                    Test
                  </button>
                  <button className="secondary small danger" onClick={() => disconnect(l.key)}>
                    Disconnect
                  </button>
                </>
              )}
              {msg[l.key] && <span className="small">{msg[l.key]}</span>}
            </div>
          </details>
        );
      })}
    </div>
  );
}
