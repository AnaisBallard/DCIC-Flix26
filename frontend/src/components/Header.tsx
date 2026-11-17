import { ArrowUpRight, Menu, Search, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { Brand } from "./Brand";
import { UserSelector } from "./UserSelector";

export function Header({
  userId,
  onUserChange,
}: {
  userId: string;
  onUserChange: (id: string) => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    navigate(`/explorar?q=${encodeURIComponent(query.trim())}`);
    setSearchOpen(false);
    setMobileOpen(false);
  }

  return (
    <header className="site-header">
      <div className="header-inner">
        <Link to="/" className="brand-link" aria-label="DCIC Flix, inicio">
          <Brand />
        </Link>
        <button
          className="mobile-menu-toggle"
          type="button"
          aria-label={mobileOpen ? "Cerrar menú" : "Abrir menú"}
          onClick={() => setMobileOpen((value) => !value)}
        >
          {mobileOpen ? <X size={21} /> : <Menu size={21} />}
        </button>
        <nav className={`main-nav${mobileOpen ? " main-nav--open" : ""}`} aria-label="Navegación principal">
          <NavLink to="/" end onClick={() => setMobileOpen(false)}>Inicio</NavLink>
          <NavLink to="/explorar" onClick={() => setMobileOpen(false)}>Explorar</NavLink>
          <a href="/#generos" onClick={() => setMobileOpen(false)}>Géneros</a>
          <a href="/#recomendaciones" onClick={() => setMobileOpen(false)}>Para ti</a>
        </nav>
        <div className="header-actions">
          {searchOpen ? (
            <form className="header-search" onSubmit={search}>
              <input
                autoFocus
                aria-label="Buscar películas"
                placeholder="Buscar película…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <button type="submit" aria-label="Buscar"><ArrowUpRight size={17} /></button>
            </form>
          ) : (
            <button className="icon-button search-toggle" type="button" aria-label="Abrir búsqueda" onClick={() => setSearchOpen(true)}>
              <Search size={19} />
            </button>
          )}
          <UserSelector userId={userId} onChange={onUserChange} />
        </div>
      </div>
    </header>
  );
}
