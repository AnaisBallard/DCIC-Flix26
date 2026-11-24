export interface GenreStyle {
  label: string;
  color: string;
  symbol: string;
}

export const genreStyles: Record<string, GenreStyle> = {
  Action: { label: "Acción", color: "#ff8c70", symbol: "↗" },
  Adventure: { label: "Aventura", color: "#bed88f", symbol: "✳" },
  Animation: { label: "Animación", color: "#c5b8ee", symbol: "◉" },
  Comedy: { label: "Comedia", color: "#f6d763", symbol: "☺" },
  Crime: { label: "Crimen", color: "#f4b1c6", symbol: "⌁" },
  Drama: { label: "Drama", color: "#b9dbe4", symbol: "✴" },
  Fantasy: { label: "Fantasía", color: "#c7b5ee", symbol: "✦" },
  Horror: { label: "Terror", color: "#ff9f87", symbol: "◒" },
  Romance: { label: "Romance", color: "#f3b4ca", symbol: "♡" },
  "Sci-Fi": { label: "Ciencia ficción", color: "#acc7fa", symbol: "✳" },
  Thriller: { label: "Suspense", color: "#c5c6e8", symbol: "⌁" },
  Western: { label: "Western", color: "#eacb8b", symbol: "✹" },
};

export function genreLabel(name: string) {
  return genreStyles[name]?.label ?? name;
}
