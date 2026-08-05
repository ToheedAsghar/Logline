import { useEffect, useState } from "react";
import { useSession } from "@/context/SessionContext";
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

const FIELD_LABEL = "block font-mono text-[10.5px] uppercase tracking-wider text-[#8A887C] mt-3 mb-1.5 first:mt-0";

export function AccountSettingsModal({ open, onClose }: AccountSettingsModalProps) {
  const { logout } = useSession();
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
      className="fixed inset-0 z-[110] flex items-start justify-center bg-black/40 px-4 pt-[8vh] pb-4 backdrop-blur-xs"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Account & settings"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[84vh] w-full max-w-[470px] flex-col overflow-y-auto rounded-xl border border-[#E3DFD2] bg-[#FFFDF7] shadow-xl"
      >
        <div className="sticky top-0 z-[2] flex items-center gap-3 border-b border-[#E3DFD2] bg-[#FFFDF7] px-5 py-4">
          <span className="font-mono text-[11px] uppercase tracking-wider text-[#8A887C]">Account &amp; settings</span>
          <span className="flex-1" />
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-md border border-[#E3DFD2] bg-[#F5F2EA] text-xs text-[#57564E] hover:bg-[#EFEBE0]"
          >
            ✕
          </button>
        </div>

        <div className="p-5">
          <div className="mb-5 flex items-center gap-3.5">
            <span className="relative flex-none">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#14603C] font-mono text-[20px] font-bold tracking-tight text-[#FFFDF7]">
                {initialsFor(profile.name)}
              </span>
              <span className="absolute -bottom-[3px] -right-[3px] h-4 w-4 rounded-full border-[3px] border-[#FFFDF7] bg-[#14603C]" />
            </span>
            <div className="min-w-0">
              <div className="text-base font-semibold text-[#191917]">{profile.name || "Unnamed"}</div>
              <div className="font-mono text-xs text-[#8A887C]">{profile.handle || "—"}</div>
            </div>
          </div>

          <label className={FIELD_LABEL}>Display name</label>
          <input
            type="text"
            value={profile.name}
            onChange={editField("name")}
            className="w-full rounded-md border border-[#E3DFD2] bg-[#F5F2EA] px-3 py-2 text-xs font-medium text-[#191917] focus:border-[#14603C] focus:outline-none"
          />

          <label className={FIELD_LABEL}>Work email</label>
          <input
            type="email"
            value={profile.email}
            onChange={editField("email")}
            className="w-full rounded-md border border-[#E3DFD2] bg-[#F5F2EA] px-3 py-2 text-xs font-medium text-[#191917] focus:border-[#14603C] focus:outline-none"
          />

          <label className={FIELD_LABEL}>Handle</label>
          <input
            type="text"
            value={profile.handle}
            onChange={editField("handle")}
            placeholder="@handle"
            className="w-full rounded-md border border-[#E3DFD2] bg-[#F5F2EA] px-3 py-2 text-xs font-medium text-[#191917] focus:border-[#14603C] focus:outline-none"
          />

          <label className={FIELD_LABEL}>Role</label>
          <input
            type="text"
            value={profile.role}
            onChange={editField("role")}
            className="w-full rounded-md border border-[#E3DFD2] bg-[#F5F2EA] px-3 py-2 text-xs font-medium text-[#191917] focus:border-[#14603C] focus:outline-none"
          />

          <label className={FIELD_LABEL}>Default standup channel</label>
          <input
            type="text"
            value={profile.channel}
            onChange={editField("channel")}
            placeholder="#channel"
            className="w-full rounded-md border border-[#E3DFD2] bg-[#F5F2EA] px-3 py-2 text-xs font-medium text-[#191917] focus:border-[#14603C] focus:outline-none"
          />

          <div className="mt-6 flex flex-wrap items-center gap-2.5 border-t border-[#E3DFD2] pt-5">
            <button
              type="button"
              onClick={logout}
              className="rounded-md border border-[#E0B8AC] bg-[#FBEEEA] px-3.5 py-2 text-xs font-medium text-[#A33A22] hover:bg-[#F7DDD6]"
            >
              Sign out
            </button>
            <span className="flex-1" />
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-[#CFCABA] bg-[#FFFDF7] px-3.5 py-2 text-xs font-medium text-[#191917] hover:bg-[#F5F2EA]"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-[#14603C] bg-[#14603C] px-4 py-2 text-xs font-semibold text-[#FFFDF7] shadow-sm hover:bg-[#0F4E31]"
            >
              Save changes
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

