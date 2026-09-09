import { FormEvent, useEffect, useState } from "react";
import { api, RegionType, RegionView } from "./api";

const REGION_TYPES: RegionType[] = ["unknown", "dialogue", "thought", "narration", "caption", "sign", "ui", "sfx"];

type RegionEditorProps = {
  region: RegionView;
  locale: string;
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
};

export function RegionEditor({ region, locale, onChanged, onDeleted }: RegionEditorProps) {
  const [source, setSource] = useState(region.source_text);
  const [target, setTarget] = useState(region.localization?.text ?? "");
  const [regionType, setRegionType] = useState<RegionType>((region.region_type as RegionType) ?? "unknown");
  const [readingOrder, setReadingOrder] = useState(region.reading_order);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // Keep editor fields aligned with refreshed server state. Do not clear operation
  // feedback here: save/approve call onChanged(), which refreshes these same props,
  // and clearing the message during that refresh races with the success feedback.
  useEffect(() => {
    setSource(region.source_text);
    setTarget(region.localization?.text ?? "");
    setRegionType((region.region_type as RegionType) ?? "unknown");
    setReadingOrder(region.reading_order);
  }, [region.id, region.source_text, region.region_type, region.reading_order, region.localization?.text, locale]);

  // A real selection/locale transition starts a new editing context, so old
  // operation feedback should not leak into it.
  useEffect(() => {
    setMessage(null);
  }, [region.id, locale]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const patch: Partial<Pick<RegionView, "source_text" | "reading_order" | "region_type">> = {};
      if (source !== region.source_text) patch.source_text = source;
      if (regionType !== region.region_type) patch.region_type = regionType;
      if (readingOrder !== region.reading_order) patch.reading_order = readingOrder;
      if (Object.keys(patch).length) await api.updateRegion(region.id, patch);
      await api.saveLocalization(region.id, locale, target, region.localization?.status === "approved" ? "approved" : "needs-review");
      await onChanged();
      setMessage("Saved");
    } catch (reason) {
      setMessage(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const localization = await api.saveLocalization(region.id, locale, target, "needs-review");
      await api.approveLocalization(localization.id);
      await onChanged();
      setMessage("Approved and reusable");
    } catch (reason) {
      setMessage(String(reason));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete this text region? This removes its per-locale edits from this page.")) return;
    setBusy(true);
    setMessage(null);
    try {
      await api.deleteRegion(region.id);
      await onDeleted();
    } catch (reason) {
      setMessage(String(reason));
      setBusy(false);
    }
  };

  return (
    <form className="region-editor" onSubmit={save}>
      <div className="region-meta">
        <span>{region.region_type}</span>
        <span>#{region.reading_order}</span>
        {region.ocr_confidence != null && <span>OCR {Math.round(region.ocr_confidence * 100)}%</span>}
      </div>
      <div className="region-structure-row">
        <label>
          Type
          <select value={regionType} onChange={(event) => setRegionType(event.target.value as RegionType)}>
            {REGION_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        <label>
          Reading order
          <input type="number" min="0" step="1" value={readingOrder} onChange={(event) => setReadingOrder(Number(event.target.value))} />
        </label>
      </div>
      {regionType === "unknown" && <small className="classification-note">Classify this region before automatic cleanup or localization.</small>}
      <label>
        Source OCR
        <textarea value={source} onChange={(event) => setSource(event.target.value)} rows={4} />
      </label>
      <label>
        {locale} localization
        <textarea value={target} onChange={(event) => setTarget(event.target.value)} rows={5} placeholder="Enter or generate a translation" />
      </label>
      <div className="editor-actions">
        <button type="submit" disabled={busy}>Save</button>
        <button type="button" className="secondary" onClick={approve} disabled={busy || !target.trim()}>Approve</button>
        <button type="button" className="danger" onClick={remove} disabled={busy}>Delete</button>
      </div>
      <div className="fit-row">
        <span>Status: {region.localization?.status ?? "untranslated"}</span>
        <span>Fit: {String(region.localization?.layout?.fitStatus ?? "—")}</span>
      </div>
      {message && <small className="inline-message">{message}</small>}
    </form>
  );
}
