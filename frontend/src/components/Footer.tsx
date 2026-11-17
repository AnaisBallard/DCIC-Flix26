import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";
import { Brand } from "./Brand";

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-main">
        <div className="footer-intro">
          <Link to="/" aria-label="DCIC Flix, inicio"><Brand footer /></Link>
          <p>Un buen título puede abrirte<br />un mundo entero.</p>
        </div>
        <div className="footer-links">
          <div><span className="footer-label">Descubre</span><Link to="/explorar">Todas las películas</Link><a href="/#generos">Géneros</a><a href="/#recomendaciones">Recomendaciones</a></div>
          <div><span className="footer-label">El proyecto</span><a href="/#sobre">Sobre DCIC-Flix</a><span>Proyecto universitario · 2026</span></div>
          <Link className="footer-back" to="/">Volver arriba <ArrowUpRight size={16} /></Link>
        </div>
      </div>
      <div className="footer-bottom"><span>© 2026 DCIC-Flix. Hecho para quienes aman las historias.</span><span>Una película a la vez <span aria-hidden="true">✳</span></span></div>
    </footer>
  );
}
