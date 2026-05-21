# Infrastructure for `datacenter.oci-incubations.com`

HTTPS + Oracle SSO gateway in front of the FastAPI backend (`:8002`) and Vite
dev server (`:5174`) running on this VM (`129.146.99.92`).

```
internet ──HTTPS──► nginx :443 ──auth_request──► oauth2-proxy :4180 ◄──OIDC──► OCI Identity Domain (Default)
```

## Files

| Path in repo | Deployed to | Purpose |
| --- | --- | --- |
| `nginx/datacenter.conf` | `/etc/nginx/sites-available/datacenter` | HTTPS vhost, `auth_request` gate, oauth2-proxy routing, large-cookie buffers, public `/signin` location. |
| `oauth2-proxy/oauth2-proxy.cfg.example` | `/etc/oauth2-proxy/oauth2-proxy.cfg` (mode 640, owner `root:oauth2-proxy`) | oauth2-proxy config. Secrets redacted — fill in from OCI Identity Domain app registration. |
| `systemd/oauth2-proxy.service` | `/etc/systemd/system/oauth2-proxy.service` | systemd unit (hardened, runs as `oauth2-proxy` user). |
| `www/signin.html` | `/var/www/datacenter/signin.html` | Public sign-in landing page (bypasses auth gate). |

## Quick recreation steps

1. Open OCI VCN Security List ingress for TCP `:443` (leave Source Port Range blank — don't repeat the bug where we set it to `443` and silently blocked everything).
2. `sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT && sudo netfilter-persistent save`
3. `sudo snap install --classic certbot && sudo certbot --nginx -d datacenter.oci-incubations.com`
4. In OCI Identity Domain → Default → Integrated applications → register a Confidential Application. Redirect URL: `https://datacenter.oci-incubations.com/oauth2/callback`. Grant types: Authorization Code + Refresh Token. Disable "Enforce grants as authorization" so any domain user can sign in.
5. In Default domain Settings → enable **Access Signing Certificate** for anonymous reads (needed for oauth2-proxy JWKS fetch).
6. Install oauth2-proxy v7.15.2+ binary to `/usr/local/bin/oauth2-proxy`. Create system user `oauth2-proxy`, mkdir `/etc/oauth2-proxy/` (mode 750, `root:oauth2-proxy`).
7. Copy this dir's files into place. Generate a fresh cookie secret with `openssl rand -base64 32 | tr -- '+/' '-_'`. Fill in Client ID, Client Secret, Identity Domain URL.
8. `sudo systemctl daemon-reload && sudo systemctl enable --now oauth2-proxy && sudo nginx -t && sudo systemctl reload nginx`

## OCI Identity Domain gotchas baked into the configs

- **Shared issuer:** discovery doc reports `issuer: https://identity.oraclecloud.com/` for every Identity Domain. `insecure_oidc_skip_issuer_verification = true` works around this; signature verification via JWKS still happens.
- **JWKS is locked down by default:** the signing cert endpoint returns 401 unless anonymous reads are explicitly enabled in domain settings.
- **ID tokens are huge:** session cookies span multiple `Set-Cookie` headers. nginx needs `proxy_buffer_size 16k` / `large_client_header_buffers 8 16k` or the callback 502s.

## Identity surfaced to upstream apps

Every authenticated request hitting `:8002` (FastAPI) or `:5174` (Vite) carries:

- `X-Forwarded-Email` — e.g. `gabrielle.lyu@oracle.com`
- `X-Forwarded-User` — Identity Domain user GUID

Use these in the backend when you need to attribute actions to a user.

## Sign-out behavior

The "Sign out" button in `frontend/src/components/layout/UserMenu.tsx` clears the local oauth2-proxy cookie and lands the user on `/signin`. The user stays there until they explicitly click "Sign in with Oracle SSO". Oracle's OIDC `userlogout` endpoint requires `id_token_hint` (which we don't expose to the browser), so we can't kill the upstream OCI SSO session — that's standard SSO behavior across most enterprise apps.

## Adding users

OCI Console → Identity & Security → Domains → Default → Users → Create user (or bulk CSV import). OCI emails them an activation link; they pick their own password. Identity Domain users have zero OCI Console / tenancy permissions.
