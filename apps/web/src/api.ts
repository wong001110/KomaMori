export type Series = { id: number; title: string; source_language: string };
export type Chapter = { id: number; series_id: number; title: string; number: number; status: string };
export type Page = { id: number; chapter_id: number; page_index: number; original_asset: string; clean_asset: string | null; width: number | null; height: number | null; processing_status: string };
export type SeriesDetail = Series & { chapters: Chapter[] };
export type ChapterDetail = Chapter & { pages: Page[] };
export type RegionType = "unknown" | "dialogue" | "thought" | "narration" | "caption" | "sign" | "ui" | "sfx";
export type Localization = { id: number; text_region_id: number; locale: string; text: string; status: "draft" | "needs-review" | "approved" | string; source: string; quality_metadata: Record<string, unknown>; layout: Record<string, unknown> };
export type RegionView = { id: number; page_id: number; region_type: RegionType | string; geometry: number[][]; source_text: string; ocr_confidence: number | null; reading_order: number; localization: Localization | null };
export type PageView = { id: number; page_index: number; width: number | null; height: number | null; original_url: string; clean_url: string | null; regions: RegionView[] };
export type ChapterView = { chapter_id: number; series_id: number; title: string; number: number; locale: string; pages: PageView[] };
export type Term = { id: number; series_id: number | null; locale: string; source: string; target: string; term_type: string; aliases: string[]; locked: boolean; notes: string };
export type QAIssue = { code: string; severity: "info" | "warning" | "error"; page_id: number; region_id: number; localization_id: number | null; message: string };
export type LocaleReadiness = "in-progress" | "review" | "ready";
export type LocaleSummary = { locale: string; translated: number; approved: number; total_regions: number; status: LocaleReadiness };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  listSeries: () => request<Series[]>("/api/series"),
  getSeries: (id: number) => request<SeriesDetail>(`/api/series/${id}`),
  createSeries: (title: string, sourceLanguage: string) => request<Series>("/api/series", { method: "POST", ...json({ title, source_language: sourceLanguage }) }),
  updateSeries: (id: number, patch: Partial<Pick<Series, "title" | "source_language">>) => request<Series>(`/api/series/${id}`, { method: "PATCH", ...json(patch) }),
  deleteSeries: (id: number) => request<void>(`/api/series/${id}`, { method: "DELETE" }),
  createChapter: (seriesId: number, title: string, number: number) => request<Chapter>(`/api/series/${seriesId}/chapters`, { method: "POST", ...json({ title, number }) }),
  getChapter: (id: number) => request<ChapterDetail>(`/api/chapters/${id}`),
  updateChapter: (id: number, patch: Partial<Pick<Chapter, "title" | "number">>) => request<Chapter>(`/api/chapters/${id}`, { method: "PATCH", ...json(patch) }),
  deleteChapter: (id: number) => request<void>(`/api/chapters/${id}`, { method: "DELETE" }),
  importChapter: async (chapterId: number, files: File[]) => {
    const form = new FormData(); files.forEach((file) => form.append("files", file));
    return request<{ chapter_id: number; pages_imported: number }>(`/api/chapters/${chapterId}/import`, { method: "POST", body: form });
  },
  replacePage: async (pageId: number, file: File) => {
    const form = new FormData(); form.append("file", file);
    return request<Page>(`/api/pages/${pageId}/asset`, { method: "PUT", body: form });
  },
  deletePage: (pageId: number) => request<void>(`/api/pages/${pageId}`, { method: "DELETE" }),
  reorderPages: (chapterId: number, pageIds: number[]) => request<Page[]>(`/api/chapters/${chapterId}/pages/order`, { method: "PUT", ...json(pageIds) }),
  analyzeChapter: (chapterId: number, replace = false) => request<{ chapter_id: number; pages_analyzed: number; pages_skipped: number; regions_created: number }>(`/api/chapters/${chapterId}/analyze?replace=${replace}`, { method: "POST" }),
  cleanChapter: (chapterId: number) => request<{ chapter_id: number; pages_cleaned: number; pages_skipped: number }>(`/api/chapters/${chapterId}/clean`, { method: "POST" }),
  createRegion: (pageId: number, geometry: number[][], readingOrder: number, regionType: RegionType = "unknown") => request<RegionView>(`/api/pages/${pageId}/regions`, { method: "POST", ...json({ region_type: regionType, geometry, source_text: "", reading_order: readingOrder }) }),
  updateRegion: (regionId: number, patch: Partial<Pick<RegionView, "source_text" | "geometry" | "reading_order" | "region_type">>) => request<RegionView>(`/api/regions/${regionId}`, { method: "PATCH", ...json(patch) }),
  deleteRegion: (regionId: number) => request<void>(`/api/regions/${regionId}`, { method: "DELETE" }),
  getChapterView: (chapterId: number, locale: string) => request<ChapterView>(`/api/chapters/${chapterId}/view/${encodeURIComponent(locale)}`),
  listLocales: (chapterId: number) => request<LocaleSummary[]>(`/api/chapters/${chapterId}/locales`),
  listTerms: (seriesId: number, locale: string) => request<Term[]>(`/api/series/${seriesId}/terms?locale=${encodeURIComponent(locale)}`),
  createTerm: (seriesId: number, locale: string, source: string, target: string, aliases: string[] = []) => request<Term>(`/api/series/${seriesId}/terms`, { method: "POST", ...json({ locale, source, target, aliases, locked: true }) }),
  saveLocalization: (regionId: number, locale: string, text: string, status = "needs-review") => request<Localization>(`/api/regions/${regionId}/localizations/${encodeURIComponent(locale)}`, { method: "PUT", ...json({ text, status }) }),
  localizeChapter: (chapterId: number, locale: string) => request<{ chapter_id: number; locale: string; created: number; reused: number; skipped: number }>(`/api/chapters/${chapterId}/localize/${encodeURIComponent(locale)}`, { method: "POST", ...json({ overwrite: false, context_regions: 3 }) }),
  qaChapter: (chapterId: number, locale: string) => request<{ chapter_id: number; locale: string; issues: QAIssue[] }>(`/api/chapters/${chapterId}/qa/${encodeURIComponent(locale)}`),
  approveLocalization: (localizationId: number) => request<{ localization_id: number; status: string; remembered: boolean }>(`/api/localizations/${localizationId}/approve`, { method: "POST" })
};
