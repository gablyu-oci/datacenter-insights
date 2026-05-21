import { useEffect, useState } from "react";
import { ChevronDown, LogOut, User as UserIcon } from "lucide-react";

interface UserInfo {
  user?: string;
  email?: string;
  preferredUsername?: string;
}

// Local sign-out clears the oauth2-proxy session, then lands on /signin
// (a public route that does NOT auto-redirect through OCI). User stays
// signed out until they explicitly click "Sign in" on that page.
const SIGN_OUT_URL = "/oauth2/sign_out?rd=%2Fsignin";

export default function UserMenu() {
  const [info, setInfo] = useState<UserInfo | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetch("/oauth2/userinfo", { credentials: "include" })
      .then((r) => (r.ok ? (r.json() as Promise<UserInfo>) : null))
      .then(setInfo)
      .catch(() => setInfo(null));
  }, []);

  if (!info?.email) return null;

  return (
    <div
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      style={{ position: "relative" }}
    >
      <div
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          padding: "4px 8px",
          background: open ? "#1e293b" : "transparent",
          borderRadius: "6px",
          cursor: "pointer",
          fontSize: "12px",
          transition: "background 0.15s",
          userSelect: "none",
        }}
      >
        <UserIcon size={14} color="#94a3b8" />
        <span style={{ color: "#94a3b8" }}>Signed in as</span>
        <span style={{ color: "white", fontWeight: 500 }}>{info.email}</span>
        <ChevronDown
          size={12}
          color="#94a3b8"
          style={{
            transform: open ? "rotate(180deg)" : undefined,
            transition: "transform 0.15s",
          }}
        />
      </div>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            marginTop: "6px",
            background: "#1e293b",
            border: "1px solid #334155",
            borderRadius: "8px",
            padding: "6px",
            minWidth: "160px",
            boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
            zIndex: 100,
          }}
        >
          <a
            href={SIGN_OUT_URL}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "8px 10px",
              borderRadius: "6px",
              color: "#fca5a5",
              textDecoration: "none",
              fontSize: "13px",
              fontWeight: 500,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "#334155";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
            }}
          >
            <LogOut size={14} />
            Sign out
          </a>
        </div>
      )}
    </div>
  );
}
