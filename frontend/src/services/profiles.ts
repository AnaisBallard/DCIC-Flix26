export interface Profile {
  id: string;
  label: string;
}

export interface ProfileState {
  profiles: Profile[];
  warning: string;
}

const storageKey = "dcic-flix-profiles";

function isProfile(value: unknown): value is Profile {
  if (typeof value !== "object" || value === null) return false;
  const profile = value as Record<string, unknown>;
  return typeof profile.id === "string" && profile.id.length > 0
    && typeof profile.label === "string" && profile.label.length > 0;
}

function persistProfiles(profiles: Profile[]) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(profiles));
    return "";
  } catch {
    return "No se pudieron guardar los perfiles; estarán disponibles solo mientras esta página siga abierta.";
  }
}

function createDefaultProfile(warning = ""): ProfileState {
  const profile = { id: `usr_${crypto.randomUUID()}`, label: "Mi perfil" };
  const persistenceWarning = persistProfiles([profile]);
  return {
    profiles: [profile],
    warning: [warning, persistenceWarning].filter(Boolean).join(" "),
  };
}

export function loadProfiles(): ProfileState {
  let saved: string | null;
  try {
    saved = localStorage.getItem(storageKey);
  } catch {
    return createDefaultProfile("No se pudieron leer los perfiles guardados.");
  }

  if (saved) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(saved);
    } catch {
      return createDefaultProfile("Los perfiles guardados tenían un formato inválido; se creó uno nuevo.");
    }

    if (Array.isArray(parsed) && parsed.length > 0 && parsed.every(isProfile)) {
      return { profiles: parsed, warning: "" };
    }
    return createDefaultProfile("Los perfiles guardados tenían un formato inválido; se creó uno nuevo.");
  }

  return createDefaultProfile();
}

export function addProfile(profiles: Profile[]): ProfileState {
  const profile = {
    id: `usr_${crypto.randomUUID()}`,
    label: `Perfil ${profiles.length + 1}`,
  };
  const next = [...profiles, profile];
  return { profiles: next, warning: persistProfiles(next) };
}
