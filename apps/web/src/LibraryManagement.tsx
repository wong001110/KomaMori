import { FormEvent } from "react";
import type { ChapterDetail, SeriesDetail } from "./api";

type SeriesManagementProps = {
  series: SeriesDetail;
  busy: boolean;
  onSave: (title: string, sourceLanguage: string) => Promise<void>;
  onDelete: () => Promise<void>;
};

export function SeriesManagement({ series, busy, onSave, onDelete }: SeriesManagementProps) {
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await onSave(String(form.get("title") ?? "").trim(), String(form.get("sourceLanguage") ?? "").trim());
  };

  return (
    <form className="management-form" key={`${series.id}:${series.title}:${series.source_language}`} onSubmit={submit}>
      <span className="kicker">Series settings</span>
      <div className="management-fields">
        <input name="title" defaultValue={series.title} aria-label="Series title" required />
        <input name="sourceLanguage" defaultValue={series.source_language} aria-label="Series source language" required />
      </div>
      <div className="management-actions">
        <button disabled={busy}>Save series</button>
        <button type="button" className="danger" disabled={busy} onClick={() => void onDelete()}>Delete series</button>
      </div>
    </form>
  );
}

type ChapterManagementProps = {
  chapter: ChapterDetail;
  busy: boolean;
  onSave: (title: string, displayNumber: string, sortOrder: number) => Promise<void>;
  onDelete: () => Promise<void>;
};

export function ChapterManagement({ chapter, busy, onSave, onDelete }: ChapterManagementProps) {
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await onSave(
      String(form.get("title") ?? "").trim(),
      String(form.get("displayNumber") ?? "").trim(),
      Number(form.get("sortOrder"))
    );
  };

  return (
    <form className="management-form chapter-management" key={`${chapter.id}:${chapter.display_number}:${chapter.sort_order}:${chapter.title}`} onSubmit={submit}>
      <span className="kicker">Chapter settings</span>
      <div className="management-fields chapter-fields">
        <input name="displayNumber" defaultValue={chapter.display_number} aria-label="Chapter display label" required />
        <input name="sortOrder" type="number" step="0.01" defaultValue={chapter.sort_order} aria-label="Chapter sort order" required />
        <input name="title" defaultValue={chapter.title} aria-label="Chapter title" required />
      </div>
      <div className="management-actions">
        <button disabled={busy}>Save chapter</button>
        <button type="button" className="danger" disabled={busy} onClick={() => void onDelete()}>Delete chapter</button>
      </div>
    </form>
  );
}
