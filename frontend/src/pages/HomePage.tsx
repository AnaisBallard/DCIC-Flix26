import { ArrowDown, ArrowRight, ArrowUpRight, CirclePlay, Compass, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { getMovies } from "../services/api";
import type { Movie } from "../types";
import { genreStyles } from "../data/genres";
import { GenreCard, type GenreItem } from "../components/GenreCard";
import { MovieCarousel } from "../components/MovieCarousel";

function SectionHeading({ eyebrow, title, action }: { eyebrow: string; title: ReactNode; action?: ReactNode }) {
  return (
    <div className="section-heading">
      <div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div>
      {action}
    </div>
  );
}

export function HomePage() {
  const [movies, setMovies] = useState<Movie[]>([]);
  const [genres, setGenres] = useState<GenreItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [genreError, setGenreError] = useState("");

  useEffect(() => {
    let active = true;
    getMovies({ pageSize: 24 })
      .then((result) => {
        if (!active) return;
        setMovies(result.items);
        setError("");
      })
      .catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    getMovies({ pageSize: 100 })
      .then((result) => {
        if (!active) return;
        const found = new Set(result.items.flatMap((movie) => movie.genres ?? []));
        setGenres([...found]
          .filter((name) => genreStyles[name])
          .slice(0, 9)
          .map((name) => ({ name, ...genreStyles[name] })));
      })
      .catch((reason: Error) => { if (active) setGenreError(reason.message); });
    return () => { active = false; };
  }, []);

  const featured = useMemo(
    () => movies.find((movie) => movie.poster && movie.plot?.trim()) ?? movies.find((movie) => movie.poster) ?? movies[0],
    [movies],
  );
  const collection = movies.slice(0, 12);

  return (
    <>
      <section className="hero-section" id="inicio">
        <div className="hero-grain" />
        <div className="hero-content">
          <div className="hero-copy">
            <p className="hero-overline"><span className="hero-star">✳</span> Un catálogo, infinitas miradas</p>
            <h1>El cine aún<br />puede <span>sorprenderte.</span></h1>
            <p className="hero-description">Historias que no sabías que necesitabas. Encuentra tu próxima película favorita, sin hacer scroll para siempre.</p>
            <div className="hero-actions">
              <Link className="button button-dark" to="/explorar">Explorar películas <ArrowRight size={17} /></Link>
              <a className="hero-text-link" href="#recomendaciones"><CirclePlay size={18} /> Descubre algo nuevo</a>
            </div>
            <div className="hero-edition"><span>ARCHIVO ABIERTO</span><span>VOL. 01 — 2026</span></div>
          </div>
          <div className="hero-art" aria-label={featured ? `Película destacada: ${featured.title?.trim()}` : "Cartel destacado"}>
            <span className="orbit orbit-one" /><span className="orbit orbit-two" />
            <div className="hero-spark hero-spark-one">✳</div><div className="hero-spark hero-spark-two">✦</div>
            <div className="hero-note">UNA HISTORIA<br />TE ESTÁ ESPERANDO <ArrowDown size={14} /></div>
            <div className="hero-poster">
              {featured?.poster ? <img src={featured.poster} alt={`Cartel de ${featured.title?.trim()}`} /> : <div className="hero-poster-placeholder"><span>UNA PELÍCULA<br />POR DESCUBRIR</span><strong>DCIC<br />FLIX</strong></div>}
              <div className="hero-poster-caption">
                <span>EN EL CATÁLOGO</span>
                <strong>{featured?.title?.trim() ?? "Elige tu próxima historia"}</strong>
                <span>{featured?.year ?? "DCIC-FLIX · 2026"}</span>
              </div>
            </div>
            <div className="hero-sticker"><span>PARA VER<br />CON OTROS<br />OJOS</span><span>✳</span></div>
            <div className="hero-index">01<span>/</span>26</div>
          </div>
          <a className="hero-scroll" href="#peliculas"><span>BAJA Y EXPLORA</span><ArrowDown size={14} /></a>
        </div>
      </section>

      <section className="home-section collection-section" id="peliculas">
        <div className="section-topline"><span>01 — EL ARCHIVO</span><span>PELÍCULAS PARA MIRAR DE OTRA MANERA</span></div>
        <SectionHeading eyebrow="Tu próxima historia empieza aquí" title="Pequeñas grandes joyas" action={<Link className="text-link" to="/explorar">Ver todo el catálogo <ArrowUpRight size={16} /></Link>} />
        {loading ? <div className="loading-row">Cargando películas del catálogo<span className="loading-dots">…</span></div> :
          error ? <div className="inline-error"><p>{error}</p><Link className="text-link" to="/explorar">Intentar desde el catálogo <ArrowRight size={16} /></Link></div> :
          movies.length ? <MovieCarousel movies={collection} /> :
          <div className="empty-note">No hay películas disponibles en el catálogo en este momento.</div>}
        <div className="archive-note"><span>✳</span> Películas y carteles del catálogo universitario.</div>
      </section>

      <section className="genre-section" id="generos">
        <div className="genre-section-inner">
          <div className="section-topline"><span>02 — CAMBIA DE RUMBO</span><span>¿QUÉ TE APETECE SENTIR?</span></div>
          <SectionHeading eyebrow="Elige tu propio camino" title={<>Un género.<br /><span>Otro universo.</span></>} action={<Compass size={29} strokeWidth={1.4} />} />
          {genres.length ? (
            <div className="genre-grid">{genres.map((genre, index) => <GenreCard genre={genre} index={index} key={genre.name} />)}</div>
          ) : <p className="genre-empty" role={genreError ? "status" : undefined}>
            {genreError ? `No se pudieron cargar los géneros: ${genreError}` : "No hay géneros disponibles para mostrar en esta selección."}
          </p>}
          <Link className="genre-all" to="/explorar">Explorar todos los géneros <ArrowUpRight size={17} /></Link>
        </div>
      </section>

      <section className="recommendation-section" id="recomendaciones">
        <div className="recommendation-copy">
          <span className="recommendation-icon"><Sparkles size={20} /></span>
          <p className="eyebrow">Una selección, a tu manera</p>
          <h2>Tenemos algo<br />para <em>ti.</em></h2>
          <p>Estamos preparando el motor que conectará tus gustos con nuevas historias. Sin recomendaciones al azar: solo sugerencias que tengan sentido.</p>
          <span className="status-pill"><span /> Motor de recomendaciones en preparación</span>
        </div>
        <div className="recommendation-art" aria-label="Ilustración editorial de DCIC Flix">
          <div className="rec-disc"><span>DCIC<br />FLIX</span></div>
          <div className="rec-orbit rec-orbit-a" /><div className="rec-orbit rec-orbit-b" />
          <span className="rec-star rec-star-a">✳</span><span className="rec-star rec-star-b">✦</span>
          <span className="rec-caption">NO ES EL ALGORITMO.<br />ES EL COMIENZO.</span>
        </div>
      </section>

      <section className="editorial-section" id="sobre">
        <div className="editorial-heading">
          <span className="editorial-number">03 / NOTAS AL MARGEN</span>
          <h2>Las buenas historias<br />no vienen en <em>fila.</em></h2>
          <p>DCIC-Flix es un proyecto universitario para descubrir el cine desde otro lugar: con curiosidad, contexto y ganas de dejarse sorprender.</p>
          <Link className="button button-outline" to="/explorar">Entrar al archivo <ArrowUpRight size={17} /></Link>
        </div>
        <div className="editorial-shape">
          <div className="editorial-frame"><span>EL PRÓXIMO<br />FOTOGRAMA<br />ES TUYO</span><i>✳</i></div>
          <span className="editorial-small">CURIOSIDAD<br />EN 24 FOTOGRAMAS</span>
        </div>
      </section>
    </>
  );
}
