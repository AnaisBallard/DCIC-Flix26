import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { CSSProperties } from "react";

export interface GenreItem {
  name: string;
  label: string;
  color: string;
  symbol: string;
}

export function GenreCard({ genre, index }: { genre: GenreItem; index: number }) {
  return (
    <Link
      className={`genre-card genre-card--${index % 6}`}
      to={`/explorar?genre=${encodeURIComponent(genre.name)}`}
      style={{ "--genre-color": genre.color } as CSSProperties}
    >
      <span className="genre-symbol">{genre.symbol}</span>
      <span className="genre-bottom"><strong>{genre.label}</strong><ArrowUpRight size={19} /></span>
      <span className="genre-original">{genre.name}</span>
    </Link>
  );
}
