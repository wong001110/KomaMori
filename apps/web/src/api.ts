export type Series = { id: number; title: string; source_language: string };
export type Chapter = { id: number; series_id: number; title: string; number: number; status: string };
export type Page = {
  id: number;
  chapter_id: number;
  page_index: number;
  original_asset: string;
  clean_asset: string | null;
  width: number | null;
  height: number | null;
  processing_status: string;
};
export type SeriesDetail = Series & { chapters: Chapter[] };
export type ChapterDetail = Chapter & { pages: Page[] };

export type Localization = {
  id: number;
  text_region_id: number;
  locale: string;
  text: string;
  status: "draft" | "needs-review" | "approved" | string;
  source: string;
  quality_metadata: Record<string, unknown>;
  layout: Record<string, unknown>;
};

export type RegionView = {
  id: number;
  page_id: number;
  region_type: string;
  geometry: number[][];
  source_text: string;
  ocr_confidence: number | null;
  reading_order: number;
  localization: Localization | null;
};

export type PageView = {
  id: number;
  page_index: number;
  width: number | null;
  height: number | null;
  original_url: string;
  clean_url: string | null;
  regions: RegionView[];
};

export type ChapterView = {
  chapter_id: number;
  series_id: number;
  title: string;
  number: number;
  locale: string;
  pages: PageView[];
};

export type Term = {
  id: number;
  series_id: number | null;
  locale: string;
  source: string;
  target: string;
  term_type: string;
  aliases: string[];
  locked: boolean;
  notes: string;
};

export type QAIssue = {
  code: string;
  severity: "info" | "warning" | "error";
  page_id: number;
  region_id: number;
  localization_id: number | null;
  message: string;
};

export type LocaleSummary = {
  locale: string;
  translated: number;
  approved: number;
  total_regions: number;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body)
});

export const api = {
  listSeries: () => request<Series[]>("/api/series"),
  getSeries: (id: number) => request<SeriesDetail>(`/api/series/${id}`),
  createSeries: (title: string, sourceLanguage: string) =>
    request<Series>("/api/series", { method: "POST", ...json({ title, source_language: sourceLanguage }) }),
  createChapter: (seriesId: number, title: string, number: number) =>
    request<Chapter>(`/api/series/${seriesId}/chapters`, { method: "POST", ...json({ title, number }) }),
  getChapter: (id: number) => request<ChapterDetail>(`/api/chapters/${id}`),
  importChapter: async (chapterId: number, files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<{ chapter_id: number; pages_imported: number }>(`/api/chapters/${chapterId}/import`, {
      method: "POST",
      body: form
    });
  },

  analyzeChapter: (chapterId: number, replace = false) =>
    request<{ chapter_id: number; pages_analyzed: number; pages_skipped: number; regions_created: number }>(
      `/api/chapters/${chapterId}/analyze?replace=${replace}`,
      { method: "POST" }
    ),
  cleanChapter: (chapterId: number) =>
    request<{ chapter_id: number; pages_cleaned: number; pages_skipped: number }>(
      `/api/chapters/${chapterId}/clean`,
      { method: "POST" }
    ),
  updateRegion: (regionId: number, patch: Partial<Pick<RegionView, "source_text" | "geometry" | "reading_order" | "region_type">>) =>
    request<RegionView>(`/api/regions/${regionId}`, { method: "PATCH", ...json(patch) }),

  getChapterView: (chapterId: number, locale: string) =>
    request<ChapterView>(`/api/chapters/${chapterId}/view/${encodeURIComponent(locale)}`),
  listLocales: (chapterId: number) => request<LocaleSummary[]>(`/api/chapters/${chapterId}/locales`),
  listTerms: (seriesId: number, locale: string) =>
    request<Term[]>(`/api/series/${seriesId}/terms?locale=${encodeURIComponent(locale)}`),
  createTerm: (seriesId: number, locale: string, source: string, target: string) =>
    request<Term>(`/api/series/${seriesId}/terms`, {
      method: "POST",
      ...json({ locale, source, target, locked: true })
    }),
  saveLocalization: (regionId: number, locale: string, text: string, status = "needs-review") =>
    request<Localization>(`/api/regions/${regionId}/localizations/${encodeURIComponent(locale)}`, {
      method: "PUT",
      ...json({ text, status })
    }),
  localizeChapter: (chapterId: number, locale: string) =>
    request<{ chapter_id: number; locale: string; created: number; reused: number; skipped: number }>(
      `/api/chapters/${chapterId}/localize/${encodeURIComponent(locale)}`,
      { method: "POST", ...json({ overwrite: false, context_regions: 3 }) }
    ),
  qaChapter: (chapterId: number, locale: string) =>
    request<{ chapter_id: number; locale: string; issues: QAIssue[] }>(
      `/api/chapters/${chapterId}/qa/${encodeURIComponent(locale)}`
    ),
  approveLocalization: (localizationId: number) =>
    request<{ localization_id: number; status: string; remembered: boolean }>(
      `/api/localizations/${localizationId}/approve`,
      { method: "POST" }
    )
};
