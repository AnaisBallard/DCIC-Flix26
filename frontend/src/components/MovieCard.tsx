import { ArrowUpRight, Star } from "lucide-react";
import { Link } from "react-router-dom";
import type { CSSProperties } from "react";
import type { Movie } from "../types";

const palettes = ["#f4b7a9", "#c5c6ef", "#d5e5a8", "#f4d985", "#bddde7"];

export function MovieCard({ movie, index = 0 }: { movie: Movie; index?: number }) {
  const rating = movie.imdb?.rating;
  return (
    <article className="movie-card" style={{ "--card-accent": palettes[index % palettes.length] } as CSSProperties}>
      <Link to={`/pelicula/${movie._id}`} className="movie-poster" aria-label={`Ver ${movie.title?.trim()}`}>
        {movie.poster ? (
          <img src={movie.poster} alt={`Cartel de ${movie.title?.trim()}`} loading="lazy" />
        ) : (
          <span className="poster-fallback"><span>DCIC<br />FLIX</span><strong>{movie.title?.trim()}</strong></span>
        )}
        <span className="poster-overlay" />
        <span className="poster-view"><ArrowUpRight size={19} /></span>
        {rating != null && <span className="poster-rating"><Star size={12} fill="currentColor" /> {rating.toFixed(1)}</span>}
      </Link>
      <div className="movie-meta">
        <Link to={`/pelicula/${movie._id}`} className="movie-title">{movie.title?.trim() || "Sin título"}</Link>
        <div className="movie-subline">
          <span>{movie.year ?? "Año desconocido"}</span>
          {movie.genres?.[0] && <><span className="meta-dot">·</span><span>{movie.genres[0]}</span></>}
        </div>
      </div>
    </article>
  );
}
