import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, Chapter, ChapterDetail, Series, SeriesDetail } from "./api";
import { ChapterManagement, SeriesManagement } from "./LibraryManagement";
import { Reader } from "./Reader";
import { Workbench } from "./Workbench";

type Mode = "library" | "workbench" | "reader";

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
  const [mode, setMode] = useState<Mode>("library");
  const [locale, setLocale] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshSeries = async () => {
    const next = await api.listSeries();
    setSeries(next);
    if (selectedSeries) setSelectedSeries(await api.getSeries(selectedSeries.id));
    if (selectedChapter) setSelectedChapter(await api.getChapter(selectedChapter.id));
  };

  const refreshSelectedChapter = async () => {
    if (!selectedChapter) return;
    setSelectedChapter(await api.getChapter(selectedChapter.id));
    if (selectedSeries) setSelectedSeries(await api.getSeries(selectedSeries.id));
  };

  useEffect(() => {
    refreshSeries().catch((reason) => setError(String(reason)));
  }, []);

  const selectedChapterSummary = useMemo(
    () => selectedSeries?.chapters.find((chapter) => chapter.id === selectedChapter?.id),
    [selectedSeries, selectedChapter]
  );

  if (mode === "workbench" && selectedChapter && selectedSeries) {
    return (
      <Workbench
        chapterId={selectedChapter.id}
        seriesId={selectedSeries.id}
        initialLocale={locale}
        onLocaleChange={setLocale}
        onBack={() => { setMode("library"); refreshSeries().catch(() => undefined); }}
        onReader={() => setMode("reader")}
      />
    );
  }

  if (mode === "reader" && selectedChapter) {
    return (
      <Reader
        chapterId={selectedChapter.id}
        initialLocale={locale}
        onLocaleChange={setLocale}
        onBack={() => setMode("library")}
        onEdit={() => setMode("workbench")}
      />
    );
  }

  const createSeries = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const created = await api.createSeries(String(form.get("title")), String(form.get("sourceLanguage")));
      setSeries(await api.listSeries());
      setSelectedSeries(await api.getSeries(created.id));
      setSelectedChapter(null);
      event.currentTarget.reset();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const chooseSeries = async (item: Series) => {
    setError(null);
    try {
      setSelectedSeries(await api.getSeries(item.id));
      setSelectedChapter(null);
    } catch (reason) {
      setError(String(reason));
    }
  };

  const saveSeries = async (title: string, sourceLanguage: string) => {
    if (!selectedSeries || !title || !sourceLanguage) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateSeries(selectedSeries.id, { title, source_language: sourceLanguage });
      setSeries(await api.listSeries());
      setSelectedSeries(await api.getSeries(selectedSeries.id));
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const deleteSeries = async () => {
    if (!selectedSeries || !window.confirm(`Delete series “${selectedSeries.title}” and all of its chapters/assets?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteSeries(selectedSeries.id);
      setSeries(await api.listSeries());
      setSelectedSeries(null);
      setSelectedChapter(null);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const createChapter = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedSeries) return;
    const form = new FormData(event.currentTarget);
    const displayNumber = String(form.get("displayNumber") ?? "").trim();
    const sortOrder = Number(form.get("sortOrder"));
    setBusy(true);
    setError(null);
    try {
      const chapter = await api.createChapter(selectedSeries.id, String(form.get("title")), displayNumber, sortOrder);
      setSelectedSeries(await api.getSeries(selectedSeries.id));
      setSelectedChapter(await api.getChapter(chapter.id));
      event.currentTarget.reset();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const chooseChapter = async (chapter: Chapter) => {
    setError(null);
    try {
      setSelectedChapter(await api.getChapter(chapter.id));
    } catch (reason) {
      setError(String(reason));
    }
  };

  const saveChapter = async (title: string, displayNumber: string, sortOrder: number) => {
    if (!selectedChapter || !selectedSeries || !title || !displayNumber || !Number.isFinite(sortOrder)) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateChapter(selectedChapter.id, { title, display_number: displayNumber, sort_order: sortOrder });
      setSelectedChapter(await api.getChapter(selectedChapter.id));
      setSelectedSeries(await api.getSeries(selectedSeries.id));
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const deleteChapter = async () => {
    if (!selectedChapter || !selectedSeries || !window.confirm(`Delete chapter ${selectedChapter.display_number} “${selectedChapter.title}” and its assets?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteChapter(selectedChapter.id);
      setSelectedChapter(null);
      setSelectedSeries(await api.getSeries(selectedSeries.id));
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const importPages = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedChapter) return;
    const input = event.currentTarget.elements.namedItem("pages") as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    if (!files.length) return;
    setBusy(true);
    setError(null);
    try {
      await api.importChapter(selectedChapter.id, files);
      await refreshSelectedChapter();
      event.currentTarget.reset();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const replacePage = async (pageId: number, file: File) => {
    setBusy(true);
    setError(null);
    try {
      await api.replacePage(pageId, file);
      await refreshSelectedChapter();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const removePage = async (pageId: number) => {
    if (!window.confirm("Delete this page? Its regions and localizations will also be removed.")) return;
    setBusy(true);
    setError(null);
    try {
      await api.deletePage(pageId);
      await refreshSelectedChapter();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const movePage = async (pageId: number, delta: number) => {
    if (!selectedChapter) return;
    const ids = selectedChapter.pages.map((page) => page.id);
    const index = ids.indexOf(pageId);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    setBusy(true);
    setError(null);
    try {
      await api.reorderPages(selectedChapter.id, ids);
      await refreshSelectedChapter();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="app-shell library-shell">
      <header className="app-header library-header">
        <div>
          <div className="brand-row"><span className="brand-mark">こ</span><strong>KomaMori</strong></div>
          <span className="eyebrow">Private manga garden</span>
        </div>
        <div className="library-hero">
          <h1>Grow one manga source into many languages.</h1>
          <p>Import once, preserve the original, then OCR, clean, localize, review and read from the same structured chapter.</p>
        </div>
        <span className="phase-pill">MVP workbench</span>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="library-grid">
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
              <button className={selectedSeries?.id === item.id ? "list-item active" : "list-item"} key={item.id} onClick={() => chooseSeries(item)}>
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
              <SeriesManagement series={selectedSeries} busy={busy} onSave={saveSeries} onDelete={deleteSeries} />
              <form className="chapter-form chapter-v2-form" onSubmit={createChapter}>
                <input name="displayNumber" placeholder="Label (1 / Extra)" aria-label="New chapter display label" required />
                <input name="sortOrder" type="number" step="0.01" placeholder="Order" aria-label="New chapter sort order" required />
                <input name="title" placeholder="Chapter title" required />
                <button disabled={busy}>Add chapter</button>
              </form>
              <div className="chapter-grid">
                {selectedSeries.chapters.map((chapter) => (
                  <button className={selectedChapter?.id === chapter.id ? "chapter-card active" : "chapter-card"} key={chapter.id} onClick={() => chooseChapter(chapter)}>
                    <span>#{chapter.display_number}</span>
                    <strong>{chapter.title}</strong>
                    <small>{chapter.status} · order {chapter.sort_order}</small>
                  </button>
                ))}
              </div>
            </>
          )}
        </section>

        <aside className="panel detail-panel">
          {!selectedChapter ? (
            <div className="placeholder">Select a chapter to import or localize.</div>
          ) : (
            <>
              <div className="panel-heading compact">
                <div><span className="kicker">Chapter {selectedChapter.display_number}</span><h2>{selectedChapter.title}</h2></div>
              </div>
              <ChapterManagement chapter={selectedChapter} busy={busy} onSave={saveChapter} onDelete={deleteChapter} />
              {!selectedChapter.pages.length ? (
                <form className="upload-box" onSubmit={importPages}>
                  <input name="pages" type="file" accept=".cbz,.zip,image/png,image/jpeg,image/webp" multiple required />
                  <button disabled={busy}>Import pages / CBZ</button>
                </form>
              ) : (
                <div className="launch-card">
                  <span className="leaf">✦</span>
                  <strong>{selectedChapter.pages.length} pages ready</strong>
                  <p>Continue in the workbench to detect text, clean pages, translate, review and approve.</p>
                  <div className="launch-actions">
                    <button onClick={() => setMode("workbench")}>Open workbench</button>
                    <button className="secondary" onClick={() => setMode("reader")}>Read {locale}</button>
                  </div>
                </div>
              )}
              <div className="page-list">
                {selectedChapter.pages.map((page, index) => (
                  <div className="page-row" key={page.id}>
                    <a href={`/api/pages/${page.id}/asset`} target="_blank" rel="noreferrer">
                      <span>{String(page.page_index).padStart(2, "0")}</span>
                      <strong>{page.width} × {page.height}</strong>
                    </a>
                    <div className="page-recovery-actions">
                      <button type="button" disabled={busy || index === 0} onClick={() => void movePage(page.id, -1)} aria-label={`Move page ${page.page_index} up`}>↑</button>
                      <button type="button" disabled={busy || index === selectedChapter.pages.length - 1} onClick={() => void movePage(page.id, 1)} aria-label={`Move page ${page.page_index} down`}>↓</button>
                      <label>
                        Replace
                        <input
                          type="file"
                          accept="image/png,image/jpeg,image/webp"
                          disabled={busy}
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) void replacePage(page.id, file);
                            event.currentTarget.value = "";
                          }}
                        />
                      </label>
                      <button type="button" className="danger" disabled={busy} onClick={() => void removePage(page.id)}>Delete</button>
                    </div>
                  </div>
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
