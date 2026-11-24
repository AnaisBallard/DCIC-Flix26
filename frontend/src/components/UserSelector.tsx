import { Check, ChevronDown, Plus, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Profile } from "../services/profiles";

export function UserSelector({
  userId,
  profiles,
  storageWarning,
  onChange,
  onAddProfile,
}: {
  userId: string;
  profiles: Profile[];
  storageWarning: string;
  onChange: (id: string) => void;
  onAddProfile: () => boolean;
}) {
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function closeOutside(event: PointerEvent) {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);

  const active = profiles.find((profile) => profile.id === userId);

  return (
    <div className="profile-wrap" ref={wrapper}>
      <button
        className="profile-trigger"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="profile-avatar"><UserRound size={16} /></span>
        <span className="profile-label">{active?.label ?? "Mi perfil"}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="profile-menu">
          <p className="menu-kicker">Perfiles de este dispositivo</p>
          {profiles.map((profile) => (
            <button
              type="button"
              className="profile-option"
              key={profile.id}
              onClick={() => { onChange(profile.id); setOpen(false); }}
            >
              <span>{profile.label}</span>
              {profile.id === userId && <Check size={16} />}
            </button>
          ))}
          <button type="button" className="profile-option profile-add" onClick={() => setOpen(onAddProfile())}>
            <Plus size={16} /> Crear un perfil local
          </button>
          {storageWarning && <p className="profile-storage-warning" role="status">{storageWarning}</p>}
        </div>
      )}
    </div>
  );
}
