export interface Profile {
  id: string;
  label: string;
}

export interface ProfileState {
  profiles: Profile[];
  userId: string;
  warning: string;
}

const storageKey = "dcic-flix-active-profile";
const defaultProfileId = "usr_0001";
const profileCount = 2000;

export const profiles: Profile[] = Array.from({ length: profileCount }, (_, index) => {
  const id = `usr_${String(index + 1).padStart(4, "0")}`;
  return { id, label: id };
});

const profileIds = new Set(profiles.map((profile) => profile.id));

export function saveProfileId(userId: string): string {
  if (!profileIds.has(userId)) {
    return "El identificador de perfil no está en la lista disponible.";
  }
  try {
    localStorage.setItem(storageKey, userId);
    return "";
  } catch {
    return "No se pudo guardar el perfil seleccionado; estará activo solo mientras esta página siga abierta.";
  }
}

export function loadProfiles(): ProfileState {
  try {
    const savedProfileId = localStorage.getItem(storageKey);
    if (savedProfileId && profileIds.has(savedProfileId)) {
      return { profiles, userId: savedProfileId, warning: "" };
    }
    if (savedProfileId) {
      return {
        profiles,
        userId: defaultProfileId,
        warning: "El perfil guardado ya no es válido; se seleccionó usr_0001.",
      };
    }
    return { profiles, userId: defaultProfileId, warning: "" };
  } catch {
    return {
      profiles,
      userId: defaultProfileId,
      warning: "No se pudieron leer los perfiles guardados; se seleccionó usr_0001.",
    };
  }
}
