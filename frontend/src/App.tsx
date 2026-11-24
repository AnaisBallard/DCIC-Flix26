import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import { AuditPage } from "./pages/AuditPage";
import { ExplorePage } from "./pages/ExplorePage";
import { HomePage } from "./pages/HomePage";
import { MovieDetailPage } from "./pages/MovieDetailPage";
import { loadProfiles, saveProfileId } from "./services/profiles";

function App() {
  const [profileState, setProfileState] = useState(loadProfiles);
  const [userId, setUserId] = useState(() => profileState.userId);

  function handleUserChange(id: string) {
    setUserId(id);
    setProfileState((current) => ({
      ...current,
      warning: saveProfileId(id),
    }));
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#contenido">Saltar al contenido</a>
      <Header
        userId={userId}
        profiles={profileState.profiles}
        storageWarning={profileState.warning}
        onUserChange={handleUserChange}
      />
      <div id="contenido">
        <Routes>
          <Route path="/" element={<HomePage userId={userId} />} />
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
