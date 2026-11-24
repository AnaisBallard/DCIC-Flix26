import { ArrowDownWideNarrow, ArrowLeft, ArrowRight, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { MovieCard } from "../components/MovieCard";
import { getMovies } from "../services/api";
import { genreLabel } from "../data/genres";
import type { Movie } from "../types";

export function ExplorePage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const genre = params.get("genre") ?? "";
  const page = Math.max(1, Number(params.get("page") ?? 1));
  const [searchText, setSearchText] = useState(query);
  const [movies, setMovies] = useState<Movie[]>([]);
  const [availableGenres, setAvailableGenres] = useState<string[]>([]);
  const [genresError, setGenresError] = useState("");
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState("title");
  const pageSize = 24;

  useEffect(() => setSearchText(query), [query]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    getMovies({ q: query || undefined, genre: genre || undefined, page, pageSize })
      .then((result) => {
        if (!active) return;
        setMovies(result.items);
        setTotal(result.total);
        setError("");
      })
      .catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [query, genre, page]);
  useEffect(() => {
    let active = true;
    getMovies({ pageSize: 100 })
      .then((result) => {
        if (active) {
          setAvailableGenres([...new Set(result.items.flatMap((movie) => movie.genres ?? []))].sort());
          setGenresError("");
        }
      })
      .catch((reason: Error) => { if (active) setGenresError(reason.message); });
    return () => { active = false; };
  }, []);

  const sortedMovies = useMemo(() => [...movies].sort((a, b) => {
    if (sort === "year") return (Number(b.year) || 0) - (Number(a.year) || 0);
    if (sort === "rating") return (b.imdb?.rating ?? 0) - (a.imdb?.rating ?? 0);
    return (a.title ?? "").localeCompare(b.title ?? "");
  }), [movies, sort]);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  function updateParams(changes: Record<string, string>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if ("q" in changes || "genre" in changes) next.delete("page");
    setParams(next);
  }

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateParams({ q: searchText.trim() });
  }

  return (
    <main className="explore-page">
      <section className="explore-intro">
        <p className="eyebrow">EL ARCHIVO ESTÁ ABIERTO <span>✳</span></p>
        <h1>Busca sin saber<br />qué <em>encontrar.</em></h1>
        <p>Un título, un género, una corazonada. Empieza por donde quieras.</p>
      </section>
      <section className="catalogue-section">
        <form className="catalogue-search" onSubmit={search}>
          <Search size={20} />
          <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Busca por título o historia…" aria-label="Buscar por título o historia" />
          {searchText && <button className="clear-search" type="button" aria-label="Borrar búsqueda" onClick={() => { setSearchText(""); updateParams({ q: "" }); }}><X size={16} /></button>}
          <button type="submit" className="button button-dark">Buscar <ArrowRight size={16} /></button>
        </form>
        <div className="filter-toolbar">
          <div className="filter-label"><SlidersHorizontal size={17} /> <span>Filtrar por</span></div>
          <div className="select-wrap">
            <select aria-label="Filtrar por género" value={genre} onChange={(event) => updateParams({ genre: event.target.value })}>
              <option value="">Todos los géneros</option>
              {availableGenres.map((item) => <option value={item} key={item}>{genreLabel(item)}</option>)}
            </select>
          </div>
          <div className="filter-count">{total.toLocaleString("es-ES")} {total === 1 ? "película" : "películas"}</div>
          <label className="sort-wrap"><ArrowDownWideNarrow size={16} /><span>Ordenar página</span>
            <select value={sort} aria-label="Ordenar películas" onChange={(event) => setSort(event.target.value)}>
              <option value="title">Título A—Z</option><option value="year">Más recientes</option><option value="rating">Mejor nota</option>
            </select>
          </label>
        </div>
        {genresError && <p className="filter-warning" role="status">No se pudieron cargar todas las opciones de género: {genresError}</p>}
        {genre && <button className="active-filter" onClick={() => updateParams({ genre: "" })}>{genreLabel(genre)}<X size={14} /></button>}
        {loading ? <div className="catalogue-loading">Buscando en el archivo<span>…</span></div> :
          error ? <div className="catalogue-error"><strong>No pudimos cargar el catálogo.</strong><p>{error}</p><button className="text-link" onClick={() => setParams(new URLSearchParams(params))}>Volver a intentar <ArrowRight size={16} /></button></div> :
          sortedMovies.length ? <>
            <div className="catalogue-grid">{sortedMovies.map((movie, index) => <MovieCard key={movie._id} movie={movie} index={index} />)}</div>
            <div className="pagination">
              <span>Página {page} de {pageCount}</span>
              <div>
                <button aria-label="Página anterior" disabled={page <= 1} onClick={() => updateParams({ page: String(page - 1) })}><ArrowLeft size={17} /></button>
                <button aria-label="Página siguiente" disabled={page >= pageCount} onClick={() => updateParams({ page: String(page + 1) })}><ArrowRight size={17} /></button>
              </div>
            </div>
          </> : <div className="catalogue-empty"><span>⌁</span><h2>No encontramos esa historia.</h2><p>Prueba con otro título o cambia el género.</p><button className="text-link" onClick={() => { setSearchText(""); setParams(new URLSearchParams()); }}>Ver todo el catálogo <ArrowRight size={16} /></button></div>}
      </section>
    </main>
  );
}
