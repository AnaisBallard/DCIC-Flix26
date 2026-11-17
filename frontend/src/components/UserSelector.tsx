import { Check, ChevronDown, Plus, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface Profile {
  id: string;
  label: string;
}

const storageKey = "dcic-flix-profiles";

function createProfile(label: string): Profile {
  return { id: `usr_${crypto.randomUUID()}`, label };
}

function loadProfiles(): Profile[] {
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      const parsed = JSON.parse(saved) as Profile[];
      if (Array.isArray(parsed) && parsed.length) return parsed;
    }
  } catch {
    // Replace invalid local preferences with a fresh local profile.
  }
  const profile = createProfile("Mi perfil");
  localStorage.setItem(storageKey, JSON.stringify([profile]));
  return [profile];
}

export function UserSelector({
  userId,
  onChange,
}: {
  userId: string;
  onChange: (id: string) => void;
}) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);

  useEffect(() => setProfiles(loadProfiles()), []);
  useEffect(() => {
    function closeOutside(event: PointerEvent) {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);

  function addProfile() {
    const next = [...profiles, createProfile(`Perfil ${profiles.length + 1}`)];
    setProfiles(next);
    localStorage.setItem(storageKey, JSON.stringify(next));
    onChange(next[next.length - 1].id);
    setOpen(false);
  }

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
          <button type="button" className="profile-option profile-add" onClick={addProfile}>
            <Plus size={16} /> Crear un perfil local
          </button>
        </div>
      )}
    </div>
  );
}
