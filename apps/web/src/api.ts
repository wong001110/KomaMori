export type Series = { id: number; title: string; source_language: string };
export type Chapter = { id: number; series_id: number; title: string; number: number; status: string };
export type Page = {
  id: number;
  chapter_id: number;
  page_index: number;
  original_asset: string;
  width: number | null;
  height: number | null;
};
export type SeriesDetail = Series & { chapters: Chapter[] };
export type ChapterDetail = Chapter & { pages: Page[] };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listSeries: () => request<Series[]>("/api/series"),
  getSeries: (id: number) => request<SeriesDetail>(`/api/series/${id}`),
  createSeries: (title: string, sourceLanguage: string) =>
    request<Series>("/api/series", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, source_language: sourceLanguage })
    }),
  createChapter: (seriesId: number, title: string, number: number) =>
    request<Chapter>(`/api/series/${seriesId}/chapters`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, number })
    }),
  getChapter: (id: number) => request<ChapterDetail>(`/api/chapters/${id}`),
  importChapter: async (chapterId: number, files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<{ chapter_id: number; pages_imported: number }>(`/api/chapters/${chapterId}/import`, {
      method: "POST",
      body: form
    });
  }
};
