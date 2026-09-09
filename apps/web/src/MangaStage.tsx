import type { CSSProperties } from "react";
import type { PageView, RegionView } from "./api";

function regionBox(region: RegionView, page: PageView) {
  const points = region.geometry.filter((point) => point.length >= 2);
  const width = page.width ?? 1;
  const height = page.height ?? 1;
  if (!points.length) return { left: 0, top: 0, width: 0, height: 0 };
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  const left = Math.min(...xs);
  const top = Math.min(...ys);
  return {
    left: (left / width) * 100,
    top: (top / height) * 100,
    width: ((Math.max(...xs) - left) / width) * 100,
    height: ((Math.max(...ys) - top) / height) * 100
  };
}

function overlayStyle(region: RegionView, page: PageView): CSSProperties {
  const box = regionBox(region, page);
  const rawFontSize = Number(region.localization?.layout?.fontSize ?? 24);
  const pageWidth = page.width ?? 1000;
  return {
    left: `${box.left}%`,
    top: `${box.top}%`,
    width: `${Math.max(box.width, 2)}%`,
    height: `${Math.max(box.height, 2)}%`,
    fontSize: `${(rawFontSize / pageWidth) * 100}cqw`,
    lineHeight: Number(region.localization?.layout?.lineHeight ?? 1.22)
  };
}

type MangaStageProps = {
  page: PageView;
  showOriginal?: boolean;
  interactive?: boolean;
  selectedRegionId?: number | null;
  onSelect?: (region: RegionView) => void;
};

export function MangaStage({ page, showOriginal = false, interactive = false, selectedRegionId, onSelect }: MangaStageProps) {
  const image = showOriginal ? page.original_url : page.clean_url ?? page.original_url;
  return (
    <div className="manga-stage" style={{ aspectRatio: `${page.width ?? 1} / ${page.height ?? 1}` }}>
      <img src={image} alt={`Page ${page.page_index}`} />
      {!showOriginal && page.regions.map((region) => {
        const text = region.localization?.text?.trim();
        if (!text && !interactive) return null;
        const lines = region.localization?.layout?.fittedLines;
        const display = Array.isArray(lines) && lines.length ? lines.join("\n") : text || region.source_text || "…";
        const className = [
          "region-overlay",
          interactive ? "interactive" : "reader-overlay",
          selectedRegionId === region.id ? "selected" : "",
          !text ? "untranslated" : ""
        ].filter(Boolean).join(" ");
        if (interactive) {
          return (
            <button
              key={region.id}
              className={className}
              style={overlayStyle(region, page)}
              onClick={() => onSelect?.(region)}
              title={`${region.region_type} · #${region.reading_order}`}
            >
              {display}
            </button>
          );
        }
        return <div key={region.id} className={className} style={overlayStyle(region, page)}>{display}</div>;
      })}
    </div>
  );
}
