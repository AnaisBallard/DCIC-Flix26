import { ArrowLeft, ArrowUpRight, CalendarDays, Clock3, MessageCircle, Star } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { MovieCarousel } from "../components/MovieCarousel";
import { getMovie, getMovies, getReviews, submitReview } from "../services/api";
import type { Movie, Review } from "../types";

export function MovieDetailPage({ userId }: { userId: string }) {
  const { movieId = "" } = useParams();
  const [movie, setMovie] = useState<Movie | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [related, setRelated] = useState<Movie[]>([]);
  const [relatedError, setRelatedError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [rating, setRating] = useState(0);
  const [hoverRating, setHoverRating] = useState(0);
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setRelated([]);
    setRelatedError("");
    Promise.all([getMovie(movieId), getReviews(movieId)])
      .then(([detail, reviewPage]) => {
        if (!active) return;
        setMovie(detail);
        setReviews(reviewPage.items);
        setError("");
        const genre = detail.genres?.[0];
        if (genre) {
          getMovies({ genre, pageSize: 8 }).then((moviePage) => {
            if (active) {
              setRelated(moviePage.items.filter((item) => item._id !== detail._id).slice(0, 6));
              setRelatedError("");
            }
          }).catch((reason: Error) => {
            if (active) {
              setRelated([]);
              setRelatedError(reason.message);
            }
          });
        } else {
          setRelated([]);
          setRelatedError("");
        }
      })
      .catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [movieId]);

  async function sendReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!movie || rating < 1 || !comment.trim()) return;
    setSending(true);
    setNotice("");
    try {
      await submitReview({ movie_id: movie._id, user_id: userId, rating, comment: comment.trim() });
      setNotice("¡Tu crítica se ha enviado! Aparecerá después de guardarse.");
      setRating(0);
      setComment("");
    } catch (reason) {
      setNotice(reason instanceof Error ? `No se pudo enviar: ${reason.message}` : "No se pudo enviar la crítica.");
    } finally {
      setSending(false);
    }
  }

  if (loading) return <main className="detail-state"><span className="eyebrow">ABRIENDO LA HISTORIA</span><p>Cargando película…</p></main>;
  if (error || !movie) return <main className="detail-state"><span className="eyebrow">ESTA PÁGINA NO ESTÁ DISPONIBLE</span><h1>No encontramos la película.</h1><p>{error}</p><Link className="text-link" to="/explorar"><ArrowLeft size={17} /> Volver al catálogo</Link></main>;

  return (
    <main className="detail-page">
      <div className="detail-back"><Link to="/explorar"><ArrowLeft size={16} /> Volver al archivo</Link><span>FICHA DE PELÍCULA <span>✳</span></span></div>
      <section className="detail-hero">
        <div className="detail-poster">
          {movie.poster ? <img src={movie.poster} alt={`Cartel de ${movie.title?.trim()}`} /> : <div className="poster-fallback detail-fallback"><span>DCIC<br />FLIX</span><strong>{movie.title?.trim()}</strong></div>}
          <span className="detail-poster-caption">ARCHIVO DCIC · {movie.year ?? "S/F"}</span>
        </div>
        <div className="detail-copy">
          <p className="eyebrow">UNA HISTORIA DEL ARCHIVO <span>✳</span></p>
          <h1>{movie.title?.trim()}</h1>
          <div className="detail-facts">
            {movie.year && <span><CalendarDays size={15} /> {movie.year}</span>}
            {movie.runtime && <span><Clock3 size={15} /> {movie.runtime} min</span>}
            {movie.rated && <span className="rated-tag">{movie.rated}</span>}
          </div>
          <div className="detail-genres">{movie.genres?.map((genre) => <Link key={genre} to={`/explorar?genre=${encodeURIComponent(genre)}`}>{genre}</Link>)}</div>
          {movie.imdb?.rating != null && <div className="detail-rating"><span><Star size={19} fill="currentColor" /> {movie.imdb.rating.toFixed(1)}</span><small>Nota IMDb{movie.imdb.votes ? ` · ${movie.imdb.votes} votos` : ""}</small></div>}
          <div className="detail-rule" />
          <p className="detail-plot">{movie.fullplot || movie.plot || "Esta película aún no tiene una sinopsis disponible en el catálogo."}</p>
          {movie.directors?.length ? <p className="detail-credit"><span>Dirección</span>{movie.directors.join(", ")}</p> : null}
          {movie.cast?.length ? <p className="detail-credit"><span>Reparto</span>{movie.cast.slice(0, 6).join(" · ")}</p> : null}
          <a className="detail-cta" href="#criticas">Deja tu impresión <ArrowUpRight size={17} /></a>
        </div>
        <span className="detail-side-note">UNA MIRADA<br />CAMBIA TODO</span>
      </section>

      <section className="reviews-section" id="criticas">
        <div className="reviews-list">
          <p className="eyebrow">LO QUE NOS DEJA</p><h2>Notas al margen<span> ({reviews.length})</span></h2>
          {reviews.length ? <div className="review-items">{reviews.map((review, index) => (
            <article className="review-item" key={review._id ?? `${review.user_id}-${index}`}>
              <div className="review-heading"><span className="review-avatar">{review.user_id.slice(-1).toUpperCase()}</span><div><strong>Espectador/a</strong><span>{review.date ? new Date(review.date).toLocaleDateString("es-ES") : "Crítica del archivo"}</span></div><span className="review-stars"><Star size={14} fill="currentColor" /> {review.rating}/5</span></div>
              <p>{review.comment}</p>
            </article>
          ))}</div> : <div className="reviews-empty"><MessageCircle size={19} /><p>Aún no hay críticas. ¿Quieres ser la primera persona en compartir una?</p></div>}
        </div>
        <form className="review-form" onSubmit={sendReview}>
          <p className="eyebrow">TU TURNO</p><h3>¿Qué te ha parecido?</h3>
          <span className="form-label">Tu nota</span>
          <div className="rating-picker" role="radiogroup" aria-label="Elige una nota">
            {[1, 2, 3, 4, 5].map((value) => <button key={value} type="button" role="radio" aria-checked={rating === value} aria-label={`${value} estrellas`} onMouseEnter={() => setHoverRating(value)} onMouseLeave={() => setHoverRating(0)} onClick={() => setRating(value)}><Star size={25} fill={(hoverRating || rating) >= value ? "currentColor" : "none"} /></button>)}
          </div>
          <label className="form-label" htmlFor="review-comment">Tu crítica</label>
          <textarea id="review-comment" rows={5} maxLength={5000} required minLength={1} placeholder="Cuéntanos qué se quedó contigo…" value={comment} onChange={(event) => setComment(event.target.value)} />
          <div className="review-form-bottom"><span>{comment.length}/5000</span><button className="button button-dark" type="submit" disabled={sending || rating < 1 || !comment.trim()}>{sending ? "Enviando…" : "Enviar crítica"} <ArrowUpRight size={16} /></button></div>
          {notice && <p className={notice.startsWith("No se pudo") ? "form-notice form-notice--error" : "form-notice"} role="status">{notice}</p>}
        </form>
      </section>

      {relatedError && <p className="detail-related-error" role="status">No se pudo cargar más del mismo género: {relatedError}</p>}
      {related.length > 0 && <section className="detail-similar"><div className="section-topline"><span>OTRAS VENTANAS</span><span>MISMO GÉNERO · {movie.genres?.[0]}</span></div><div className="section-heading"><div><p className="eyebrow">Sigue explorando</p><h2>Más historias de {movie.genres?.[0]}</h2></div><Link className="text-link" to={`/explorar?genre=${encodeURIComponent(movie.genres?.[0] ?? "")}`}>Ver género <ArrowUpRight size={16} /></Link></div><MovieCarousel movies={related} /></section>}
    </main>
  );
}
