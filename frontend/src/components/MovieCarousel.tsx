import { ArrowLeft, ArrowRight } from "lucide-react";
import { useRef } from "react";
import type { Movie } from "../types";
import { MovieCard } from "./MovieCard";

export function MovieCarousel({ movies }: { movies: Movie[] }) {
  const track = useRef<HTMLDivElement>(null);
  function move(direction: number) {
    track.current?.scrollBy({ left: direction * 360, behavior: "smooth" });
  }
  return (
    <div className="carousel-shell">
      <div className="carousel-controls">
        <button className="carousel-arrow" aria-label="Películas anteriores" onClick={() => move(-1)}><ArrowLeft size={18} /></button>
        <button className="carousel-arrow" aria-label="Más películas" onClick={() => move(1)}><ArrowRight size={18} /></button>
      </div>
      <div className="movie-carousel" ref={track}>
        {movies.map((movie, index) => <MovieCard key={movie._id} movie={movie} index={index} />)}
      </div>
    </div>
  );
}
