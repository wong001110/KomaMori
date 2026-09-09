import { FormEvent, useEffect, useState } from "react";
import { api, RegionView } from "./api";

type RegionEditorProps = {
  region: RegionView;
  locale: string;
  onChanged: () => Promise<void>;
};

export function RegionEditor({ region, locale, onChanged }: RegionEditorProps) {
  const [source, setSource] = useState(region.source_text);
  const [target, setTarget] = useState(region.localization?.text ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setSource(region.source_text);
    setTarget(region.localization?.text ?? "");
    setMessage(null);
  }, [region.id, region.source_text, region.localization?.text, locale]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      if (source !== region.source_text) await api.updateRegion(region.id, { source_text: source });
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

  return (
    <form className="region-editor" onSubmit={save}>
      <div className="region-meta">
        <span>{region.region_type}</span>
        <span>#{region.reading_order}</span>
        {region.ocr_confidence != null && <span>OCR {Math.round(region.ocr_confidence * 100)}%</span>}
      </div>
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
      </div>
      <div className="fit-row">
        <span>Status: {region.localization?.status ?? "untranslated"}</span>
        <span>Fit: {String(region.localization?.layout?.fitStatus ?? "—")}</span>
      </div>
      {message && <small className="inline-message">{message}</small>}
    </form>
  );
}
