import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, ChapterView, LocaleSummary, QAIssue, RegionView, Term } from "./api";
import { MangaStage } from "./MangaStage";
import { RegionEditor } from "./RegionEditor";

const COMMON_LOCALES = ["en", "zh-TW", "zh-CN", "ms", "ko", "es"];

type WorkbenchProps = {
  chapterId: number;
  seriesId: number;
  initialLocale: string;
  onLocaleChange: (locale: string) => void;
  onBack: () => void;
  onReader: () => void;
};

export function Workbench({ chapterId, seriesId, initialLocale, onLocaleChange, onBack, onReader }: WorkbenchProps) {
  const [locale, setLocale] = useState(initialLocale);
  const [view, setView] = useState<ChapterView | null>(null);
  const [terms, setTerms] = useState<Term[]>([]);
  const [locales, setLocales] = useState<LocaleSummary[]>([]);
  const [pageId, setPageId] = useState<number | null>(null);
  const [regionId, setRegionId] = useState<number | null>(null);
  const [drawMode, setDrawMode] = useState(false);
  const [issues, setIssues] = useState<QAIssue[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    const [nextView, nextTerms, nextLocales] = await Promise.all([
      api.getChapterView(chapterId, locale),
      api.listTerms(seriesId, locale),
      api.listLocales(chapterId)
    ]);
    setView(nextView);
    setTerms(nextTerms);
    setLocales(nextLocales);
    const validPage = nextView.pages.find((item) => item.id === pageId) ?? nextView.pages[0] ?? null;
    setPageId(validPage?.id ?? null);
    if (regionId && !validPage?.regions.some((region) => region.id === regionId)) setRegionId(null);
  };

  useEffect(() => {
    setError(null);
    reload().catch((reason) => setError(String(reason)));
    onLocaleChange(locale);
  }, [chapterId, locale]);

  const page = useMemo(() => view?.pages.find((item) => item.id === pageId) ?? view?.pages[0] ?? null, [view, pageId]);
  const selectedRegion = useMemo(
    () => page?.regions.find((region) => region.id === regionId) ?? null,
    [page, regionId]
  );

  const run = async (task: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await task();
      await reload();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const addTerm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const source = String(form.get("source") ?? "").trim();
    const target = String(form.get("target") ?? "").trim();
    const aliases = String(form.get("aliases") ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    if (!source || !target) return;
    await run(() => api.createTerm(seriesId, locale, source, target, aliases));
    event.currentTarget.reset();
  };

  const runQA = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.qaChapter(chapterId, locale);
      setIssues(result.issues);
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const selectRegion = (region: RegionView) => {
    setDrawMode(false);
    setRegionId(region.id);
  };

  const changeGeometry = async (region: RegionView, geometry: number[][]) => {
    setBusy(true);
    setError(null);
    try {
      await api.updateRegion(region.id, { geometry });
      await reload();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const createRegion = async (geometry: number[][]) => {
    if (!page) return;
    setBusy(true);
    setError(null);
    try {
      const nextOrder = Math.max(0, ...page.regions.map((region) => region.reading_order)) + 1;
      const created = await api.createRegion(page.id, geometry, nextOrder, "unknown");
      setRegionId(created.id);
      setDrawMode(false);
      await reload();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const afterDelete = async () => {
    setRegionId(null);
    await reload();
  };

  return (
    <main className="app-shell workbench-shell">
      <header className="app-header compact-header">
        <div>
          <button className="text-button" onClick={onBack}>← Library</button>
          <div className="brand-row"><span className="brand-mark">こ</span><strong>KomaMori</strong></div>
        </div>
        <div className="chapter-title">
          <span className="kicker">Localization workbench</span>
          <h1>{view ? `#${view.display_number} ${view.title}` : "Loading chapter…"}</h1>
        </div>
        <div className="header-actions">
          <label className="locale-control">
            Locale
            <input
              list="locale-options"
              value={locale}
              onChange={(event) => setLocale(event.target.value.trim())}
              aria-label="Target locale"
            />
            <datalist id="locale-options">
              {[...new Set([...COMMON_LOCALES, ...locales.map((item) => item.locale)])].map((item) => <option key={item} value={item} />)}
            </datalist>
          </label>
          <button className="primary" onClick={onReader}>Read</button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="workbench-toolbar">
        <button onClick={() => run(() => api.analyzeChapter(chapterId))} disabled={busy}>Detect + OCR</button>
        <button onClick={() => run(() => api.cleanChapter(chapterId))} disabled={busy}>Clean pages</button>
        <button onClick={() => run(() => api.localizeChapter(chapterId, locale))} disabled={busy}>AI localize</button>
        <button onClick={runQA} disabled={busy}>Run QA</button>
        <button className={drawMode ? "tool-active" : ""} onClick={() => { setDrawMode((value) => !value); setRegionId(null); }} disabled={busy || !page}>
          {drawMode ? "Cancel add" : "+ Add region"}
        </button>
        <span className="toolbar-note">Detected regions start as unknown. Classify them before automatic cleanup/localization.</span>
      </section>

      <section className="workbench-grid">
        <aside className="side-card page-sidebar">
          <div className="section-title"><span>Pages</span><strong>{view?.pages.length ?? 0}</strong></div>
          <div className="page-buttons">
            {view?.pages.map((item) => (
              <button key={item.id} className={item.id === page?.id ? "page-button active" : "page-button"} onClick={() => { setPageId(item.id); setRegionId(null); setDrawMode(false); }}>
                <span>{String(item.page_index).padStart(2, "0")}</span>
                <small>{item.regions.length} regions</small>
              </button>
            ))}
          </div>
          <div className="locale-progress">
            <span className="kicker">Locales</span>
            {locales.length ? locales.map((item) => (
              <button key={item.locale} onClick={() => setLocale(item.locale)} className={item.locale === locale ? "locale-row active" : "locale-row"}>
                <strong>{item.locale}</strong>
                <span>{item.translated}/{item.total_regions}</span>
              </button>
            )) : <small>No translations yet.</small>}
          </div>
        </aside>

        <section className="canvas-card">
          {page ? (
            <>
              <div className="canvas-meta">
                <span>Page {page.page_index}</span>
                <span>{drawMode ? "Draw a box to add an unknown region" : selectedRegion ? "Drag to move · handle to resize" : page.clean_url ? "clean asset" : "original fallback"}</span>
              </div>
              <MangaStage
                page={page}
                interactive
                selectedRegionId={regionId}
                drawMode={drawMode}
                onSelect={selectRegion}
                onGeometryChange={changeGeometry}
                onCreateRegion={createRegion}
              />
            </>
          ) : <div className="large-placeholder">Import pages to begin.</div>}
        </section>

        <aside className="right-stack">
          <section className="side-card editor-card">
            <div className="section-title"><span>Region</span><strong>{selectedRegion ? `#${selectedRegion.reading_order}` : "—"}</strong></div>
            {selectedRegion ? <RegionEditor region={selectedRegion} locale={locale} onChanged={reload} onDeleted={afterDelete} /> : <div className="small-placeholder">{drawMode ? "Draw a rectangle on the page." : "Select a text region on the page."}</div>}
          </section>

          <section className="side-card term-card">
            <div className="section-title"><span>Locked terms</span><strong>{terms.length}</strong></div>
            <form className="term-form" onSubmit={addTerm}>
              <input name="source" placeholder="Source term" />
              <input name="target" placeholder={`${locale} term`} />
              <input name="aliases" className="term-alias-input" placeholder="Aliases (comma-separated)" />
              <button disabled={busy}>Lock</button>
            </form>
            <div className="term-list">
              {terms.slice(0, 8).map((term) => (
                <div key={term.id}>
                  <span>{term.source}{term.aliases.length ? <small className="term-aliases"> aka {term.aliases.join(", ")}</small> : null}</span>
                  <strong>{term.target}</strong>
                </div>
              ))}
            </div>
          </section>

          <section className="side-card qa-card">
            <div className="section-title"><span>QA</span><strong>{issues.length}</strong></div>
            {!issues.length ? <small>Run QA to surface deterministic issues.</small> : (
              <div className="issue-list">
                {issues.map((issue, index) => (
                  <button key={`${issue.code}-${issue.region_id}-${index}`} onClick={() => { setPageId(issue.page_id); setRegionId(issue.region_id); setDrawMode(false); }} className={`issue ${issue.severity}`}>
                    <strong>{issue.code}</strong><span>{issue.message}</span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </aside>
      </section>
    </main>
  );
}
