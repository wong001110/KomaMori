const steps = ["Import", "Structure", "Localize", "Review", "Read"];

export default function App() {
  return (
    <main className="shell">
      <header className="hero">
        <span className="eyebrow">KomaMori · Phase 0</span>
        <h1>Your multilingual manga workspace.</h1>
        <p>
          Turn manga pages into structured text regions, reusable localizations, and a private reading library.
        </p>
      </header>

      <section className="flow" aria-label="KomaMori workflow">
        {steps.map((step, index) => (
          <div className="step" key={step}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{step}</strong>
          </div>
        ))}
      </section>

      <section className="empty-state">
        <div>
          <span className="leaf">✦</span>
          <h2>The library is empty.</h2>
          <p>Import will be enabled in the next phase.</p>
        </div>
      </section>
    </main>
  );
}
