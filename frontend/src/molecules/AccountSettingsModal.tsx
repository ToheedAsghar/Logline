import { useEffect, useState } from "react";
import { Button, Input } from "@/atoms";
import { useSession } from "@/context/SessionContext";
import { useTheme } from "@/context/ThemeContext";
import { me } from "@/repositories/api/auth";

export interface AccountSettingsModalProps {
  open: boolean;
  onClose: () => void;
}

interface ProfileFields {
  name: string;
  email: string;
  handle: string;
  role: string;
  channel: string;
}

// Populated from GET /auth/me when the modal opens. Handle/role/channel have
// no backend fields yet, so those stay as the handoff's hard-coded starting
// values — editing here is local-only, same as the handoff's `saveProfile()`
// (closes the modal, doesn't persist anywhere).
const DEFAULT_PROFILE: ProfileFields = {
  name: "",
  email: "",
  handle: "",
  role: "",
  channel: "",
};

function initialsFor(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  return (
    trimmed
      .split(/\s+/)
      .map((word) => word[0] ?? "")
      .slice(0, 2)
      .join("")
      .toUpperCase() || "?"
  );
}

const FIELD_LABEL = "block font-mono text-[10.5px] uppercase tracking-wider text-faint mt-3 mb-1.5 first:mt-0";

/**
 * "Account & settings" — the modal from the handoff (Logline.html:
 * `accountOpen`/`openAccount`/`closeAccount`), opened from the avatar button
 * in `AppShell`. This is the only place in the app that profile editing and
 * the Light/Dark toggle live; there is no other UI for either.
 */
export function AccountSettingsModal({ open, onClose }: AccountSettingsModalProps) {
  const { logout } = useSession();
  const { theme, setLight, setDark } = useTheme();
  const [profile, setProfile] = useState<ProfileFields>(DEFAULT_PROFILE);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    me().then((user) => {
      if (cancelled) return;
      setProfile((prev) => ({ ...prev, name: user.name ?? "", email: user.email }));
    });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const editField = (field: keyof ProfileFields) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setProfile((prev) => ({ ...prev, [field]: e.target.value }));

  return (
    <div
      className="fixed inset-0 z-[110] flex items-start justify-center bg-black/50 px-4 pt-[8vh] pb-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Account & settings"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[84vh] w-full max-w-[470px] flex-col overflow-y-auto rounded-2xl border border-border-2 bg-surface shadow-elevated"
      >
        <div className="sticky top-0 z-[2] flex items-center gap-3 border-b border-border bg-surface px-5 py-4">
          <span className="font-mono text-[11px] uppercase tracking-wider text-faint">Account &amp; settings</span>
          <span className="flex-1" />
          <Button variant="secondary" size="sm" iconOnly aria-label="Close" onClick={onClose} icon="✕" />
        </div>

        <div className="p-5">
          <div className="mb-5 flex items-center gap-3.5">
            <span className="relative flex-none">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-accent to-accent-dim font-mono text-[22px] font-bold tracking-tight text-accent-ink shadow-[0_6px_18px_var(--color-accent-soft)]">
                {initialsFor(profile.name)}
              </span>
              <span className="absolute -bottom-[3px] -right-[3px] h-4 w-4 rounded-full border-[3px] border-surface bg-accent" />
            </span>
            <div className="min-w-0">
              <div className="text-base font-semibold">{profile.name || "Unnamed"}</div>
              <div className="font-mono text-xs text-faint">{profile.handle || "—"}</div>
            </div>
          </div>

          <label className={FIELD_LABEL}>Display name</label>
          <Input value={profile.name} onChange={editField("name")} />

          <label className={FIELD_LABEL}>Work email</label>
          <Input type="email" value={profile.email} onChange={editField("email")} />

          <label className={FIELD_LABEL}>Handle</label>
          <Input value={profile.handle} onChange={editField("handle")} placeholder="@handle" />

          <label className={FIELD_LABEL}>Role</label>
          <Input value={profile.role} onChange={editField("role")} />

          <label className={FIELD_LABEL}>Default standup channel</label>
          <Input value={profile.channel} onChange={editField("channel")} placeholder="#channel" />

          <label className={FIELD_LABEL}>Appearance</label>
          <div className="flex w-fit gap-1 rounded-[11px] border border-border bg-bg p-1">
            <button
              type="button"
              onClick={setLight}
              className={`flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-semibold transition-colors ${
                theme === "light" ? "bg-accent text-accent-ink shadow-sm" : "text-muted"
              }`}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="4.2" />
                <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8" />
              </svg>
              Light
            </button>
            <button
              type="button"
              onClick={setDark}
              className={`flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-semibold transition-colors ${
                theme === "dark" ? "bg-accent text-accent-ink shadow-sm" : "text-muted"
              }`}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a7 7 0 1 0 11 11z" />
              </svg>
              Dark
            </button>
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-2.5 border-t border-border pt-5">
            <Button variant="danger" size="md" onClick={logout}>
              Sign out
            </Button>
            <span className="flex-1" />
            <Button variant="secondary" size="md" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="md" onClick={onClose}>
              Save changes
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
