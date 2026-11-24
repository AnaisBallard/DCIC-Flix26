import { Check, ChevronDown, Search, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Profile } from "../services/profiles";

export function UserSelector({
  userId,
  profiles,
  storageWarning,
  onChange,
}: {
  userId: string;
  profiles: Profile[];
  storageWarning: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapper = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function closeOutside(event: PointerEvent) {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);

  const active = profiles.find((profile) => profile.id === userId);
  const matches = profiles.filter((profile) =>
    profile.id.toLowerCase().includes(query.trim().toLowerCase()),
  );
  const visibleProfiles = matches.slice(0, 50);

  return (
    <div className="profile-wrap" ref={wrapper}>
      <button
        className="profile-trigger"
        type="button"
        aria-label={`Perfil activo ${active?.id ?? userId}`}
        aria-expanded={open}
        title={active?.id ?? userId}
        onClick={() => {
          if (open) setQuery("");
          setOpen(!open);
        }}
      >
        <span className="profile-avatar"><UserRound size={16} /></span>
        <span className="profile-label">{active?.label ?? "Mi perfil"}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="profile-menu">
          <p className="menu-kicker">Selecciona un perfil · usr_0001–usr_2000</p>
          <label className="profile-search">
            <Search size={15} />
            <input
              aria-label="Buscar perfil"
              autoComplete="off"
              placeholder="Buscar por identificador…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <p className="profile-results-count">
            {matches.length === 0
              ? "No hay perfiles coincidentes."
              : `Mostrando ${visibleProfiles.length} de ${matches.length} resultados.`}
          </p>
          <div className="profile-options">
            {visibleProfiles.map((profile) => (
              <button
                type="button"
                className="profile-option"
                key={profile.id}
                aria-current={profile.id === userId ? "true" : undefined}
                onClick={() => {
                  onChange(profile.id);
                  setOpen(false);
                  setQuery("");
                }}
              >
                <span>{profile.label}</span>
                {profile.id === userId && <Check size={16} />}
              </button>
            ))}
          </div>
          {storageWarning && <p className="profile-storage-warning" role="status">{storageWarning}</p>}
        </div>
      )}
    </div>
  );
}
