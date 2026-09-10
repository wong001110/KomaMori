import { useEffect, useMemo, useState } from "react";
import { api, ChapterView, LocaleSummary } from "./api";
import { MangaStage } from "./MangaStage";

type ReaderProps = {
  chapterId: number;
  initialLocale: string;
  onLocaleChange: (locale: string) => void;
  onBack: () => void;
  onEdit: () => void;
};

export function Reader({ chapterId, initialLocale, onLocaleChange, onBack, onEdit }: ReaderProps) {
  const [locale, setLocale] = useState(initialLocale);
  const [view, setView] = useState<ChapterView | null>(null);
  const [locales, setLocales] = useState<LocaleSummary[]>([]);
  const [showOriginal, setShowOriginal] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    Promise.all([api.getChapterView(chapterId, locale), api.listLocales(chapterId)])
      .then(([nextView, nextLocales]) => { setView(nextView); setLocales(nextLocales); })
      .catch((reason) => setError(String(reason)));
    onLocaleChange(locale);
  }, [chapterId, locale]);

  const readiness = useMemo(() => locales.find((item) => item.locale === locale) ?? null, [locales, locale]);
  const readinessLabel = readiness?.status === "ready" ? "Ready" : readiness?.status === "review" ? "Review" : "Partial";

  return (
    <main className="reader-shell">
      <header className="reader-bar">
        <button className="text-button" onClick={onBack}>← Library</button>
        <div className="reader-title">
          <span className="kicker">KomaMori Reader</span>
          <strong>{view ? `#${view.display_number} ${view.title}` : "Loading…"}</strong>
          {!showOriginal && <span className={`readiness-badge status-${readiness?.status ?? "in-progress"}`}>{readinessLabel}</span>}
        </div>
        <div className="reader-controls">
          <select value={locale} onChange={(event) => setLocale(event.target.value)}>
            {[...new Set([locale, ...locales.map((item) => item.locale)])].map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <button className={showOriginal ? "toggle active" : "toggle"} onClick={() => setShowOriginal((value) => !value)}>{showOriginal ? "Original" : "Localized"}</button>
          <button onClick={onEdit}>Edit</button>
        </div>
      </header>
      {error && <div className="error-banner reader-error">{error}</div>}
      {!showOriginal && readiness && readiness.status !== "ready" && (
        <div className="reader-readiness-note">
          <strong>{readiness.status === "review" ? "Translation requires review before release." : "Partial or unresolved localization."}</strong>
          <span>{readiness.translated}/{readiness.total_regions} translated · {readiness.approved}/{readiness.total_regions} approved</span>
        </div>
      )}
      {!showOriginal && !readiness && view && (
        <div className="reader-readiness-note">
          <strong>No localization progress is recorded for {locale}.</strong>
          <span>Open the workbench to add translations before treating this locale as ready.</span>
        </div>
      )}
      <section className="reader-pages">
        {view?.pages.map((page) => (
          <article className="reader-page" key={page.id}>
            <MangaStage page={page} showOriginal={showOriginal} />
          </article>
        ))}
        {view && !view.pages.length && <div className="large-placeholder">This chapter has no pages yet.</div>}
      </section>
    </main>
  );
}
