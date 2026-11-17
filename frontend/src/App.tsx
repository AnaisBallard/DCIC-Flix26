import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import { AuditPage } from "./pages/AuditPage";
import { ExplorePage } from "./pages/ExplorePage";
import { HomePage } from "./pages/HomePage";
import { MovieDetailPage } from "./pages/MovieDetailPage";

const profileStorageKey = "dcic-flix-profiles";

function initialUserId() {
  try {
    const stored = localStorage.getItem(profileStorageKey);
    if (stored) {
      const profiles = JSON.parse(stored) as { id?: string }[];
      if (Array.isArray(profiles) && profiles[0]?.id) return profiles[0].id;
    }
  } catch {
    localStorage.removeItem(profileStorageKey);
  }
  const profile = { id: `usr_${crypto.randomUUID()}`, label: "Mi perfil" };
  localStorage.setItem(profileStorageKey, JSON.stringify([profile]));
  return profile.id;
}

function App() {
  const [userId, setUserId] = useState(initialUserId);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#contenido">Saltar al contenido</a>
      <Header userId={userId} onUserChange={setUserId} />
      <div id="contenido">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/explorar" element={<ExplorePage />} />
          <Route path="/pelicula/:movieId" element={<MovieDetailPage userId={userId} />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="*" element={<main className="detail-state"><span className="eyebrow">404 · FUERA DEL ARCHIVO</span><h1>Esta historia no está aquí.</h1><p>Puede que el enlace haya cambiado.</p><a className="text-link" href="/"><span>Volver al inicio</span></a></main>} />
        </Routes>
      </div>
      <Footer />
    </div>
  );
}

export default App;
