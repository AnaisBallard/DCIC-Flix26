function App() {
  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="border-b border-white/10">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <a className="text-xl font-bold tracking-tight text-red-500" href="/">
            DCIC <span className="text-zinc-100">FLIX</span>
          </a>
          <span className="rounded-full border border-white/15 px-3 py-1 text-xs text-zinc-400">
            Projet universitaire
          </span>
        </nav>
      </header>

      <section className="mx-auto flex max-w-6xl flex-col px-6 pb-24 pt-24">
        <p className="mb-5 text-sm font-semibold uppercase tracking-[0.25em] text-red-400">
          DCIC-Flix26
        </p>
        <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-6xl">
          Votre cinéma, prêt à prendre forme.
        </h1>
        <p className="mt-6 max-w-xl text-lg leading-8 text-zinc-400">
          La plateforme et ses services sont en cours de préparation. Le
          catalogue universitaire sera présenté ici une fois son intégration
          développée.
        </p>
        <div className="mt-12 rounded-2xl border border-white/10 bg-white/[0.03] p-6 sm:p-8">
          <h2 className="text-lg font-medium">Catalogue en préparation</h2>
          <p className="mt-2 text-sm leading-6 text-zinc-400">
            Aucune fiche de film de démonstration n’est affichée. Les données
            seront connectées depuis le dataset du projet.
          </p>
        </div>
      </section>
    </main>
  );
}

export default App;
