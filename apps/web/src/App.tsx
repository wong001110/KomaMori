import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, Chapter, ChapterDetail, Series, SeriesDetail } from "./api";

function EmptyLibrary() {
  return (
    <div className="empty-state">
      <span className="leaf">✦</span>
      <h2>Your forest is quiet.</h2>
      <p>Create a series, then add a chapter and its manga pages.</p>
    </div>
  );
}

export default function App() {
  const [series, setSeries] = useState<Series[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<SeriesDetail | null>(null);
  const [selectedChapter, setSelectedChapter] = useState<ChapterDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshSeries = async () => {
    const next = await api.listSeries();
    setSeries(next);
    if (selectedSeries) {
      setSelectedSeries(await api.getSeries(selectedSeries.id));
    }
  };

  useEffect(() => {
    refreshSeries().catch((reason) => setError(String(reason)));
  }, []);

  const selectedChapterSummary = useMemo(
    () => selectedSeries?.chapters.find((chapter) => chapter.id === selectedChapter?.id),
    [selectedSeries, selectedChapter]
  );

  const createSeries = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const created = await api.createSeries(String(form.get("title")), String(form.get("sourceLanguage")));
      await refreshSeries();
      setSelectedSeries(await api.getSeries(created.id));
      event.currentTarget.reset();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const chooseSeries = async (item: Series) => {
    setSelectedSeries(await api.getSeries(item.id));
    setSelectedChapter(null);
  };

  const createChapter = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedSeries) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const chapter = await api.createChapter(
        selectedSeries.id,
        String(form.get("title")),
        Number(form.get("number"))
      );
      setSelectedSeries(await api.getSeries(selectedSeries.id));
      setSelectedChapter(await api.getChapter(chapter.id));
      event.currentTarget.reset();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const chooseChapter = async (chapter: Chapter) => setSelectedChapter(await api.getChapter(chapter.id));

  const importPages = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedChapter) return;
    const input = event.currentTarget.elements.namedItem("pages") as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    if (!files.length) return;
    setBusy(true);
    try {
      await api.importChapter(selectedChapter.id, files);
      setSelectedChapter(await api.getChapter(selectedChapter.id));
      if (selectedSeries) setSelectedSeries(await api.getSeries(selectedSeries.id));
      event.currentTarget.reset();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <span className="eyebrow">KomaMori</span>
          <h1>Manga, tended into many languages.</h1>
        </div>
        <span className="phase-pill">Structured core</span>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="workspace">
        <aside className="panel library-panel">
          <div className="panel-heading">
            <div><span className="kicker">Library</span><h2>Series</h2></div>
            <span>{series.length}</span>
          </div>
          <form className="stack-form" onSubmit={createSeries}>
            <input name="title" placeholder="Series title" required />
            <div className="form-row">
              <input name="sourceLanguage" defaultValue="ja" aria-label="Source language" />
              <button disabled={busy}>Add</button>
            </div>
          </form>
          <div className="item-list">
            {series.map((item) => (
              <button
                className={selectedSeries?.id === item.id ? "list-item active" : "list-item"}
                key={item.id}
                onClick={() => chooseSeries(item)}
              >
                <strong>{item.title}</strong><span>{item.source_language.toUpperCase()}</span>
              </button>
            ))}
          </div>
        </aside>

        <section className="panel chapter-panel">
          {!selectedSeries ? (
            series.length ? <div className="placeholder">Choose a series to continue.</div> : <EmptyLibrary />
          ) : (
            <>
              <div className="panel-heading">
                <div><span className="kicker">{selectedSeries.source_language}</span><h2>{selectedSeries.title}</h2></div>
                <span>{selectedSeries.chapters.length} chapters</span>
              </div>
              <form className="chapter-form" onSubmit={createChapter}>
                <input name="number" type="number" step="0.1" min="0" placeholder="#" required />
                <input name="title" placeholder="Chapter title" required />
                <button disabled={busy}>Add chapter</button>
              </form>
              <div className="chapter-grid">
                {selectedSeries.chapters.map((chapter) => (
                  <button
                    className={selectedChapter?.id === chapter.id ? "chapter-card active" : "chapter-card"}
                    key={chapter.id}
                    onClick={() => chooseChapter(chapter)}
                  >
                    <span>#{chapter.number}</span>
                    <strong>{chapter.title}</strong>
                    <small>{chapter.status}</small>
                  </button>
                ))}
              </div>
            </>
          )}
        </section>

        <aside className="panel detail-panel">
          {!selectedChapter ? (
            <div className="placeholder">Select a chapter to import pages.</div>
          ) : (
            <>
              <div className="panel-heading compact">
                <div><span className="kicker">Chapter {selectedChapter.number}</span><h2>{selectedChapter.title}</h2></div>
              </div>
              {!selectedChapter.pages.length && (
                <form className="upload-box" onSubmit={importPages}>
                  <input name="pages" type="file" accept=".cbz,.zip,image/png,image/jpeg,image/webp" multiple required />
                  <button disabled={busy}>Import pages / CBZ</button>
                </form>
              )}
              <div className="page-list">
                {selectedChapter.pages.map((page) => (
                  <a className="page-row" href={`/api/pages/${page.id}/asset`} target="_blank" key={page.id}>
                    <span>{String(page.page_index).padStart(2, "0")}</span>
                    <strong>{page.width} × {page.height}</strong>
                  </a>
                ))}
              </div>
              {selectedChapterSummary && <small className="muted">Status: {selectedChapterSummary.status}</small>}
            </>
          )}
        </aside>
      </section>
    </main>
  );
}
