import { type CSSProperties, type PointerEvent, useRef, useState } from "react";
import type { PageView, RegionView } from "./api";

type Box = { left: number; top: number; width: number; height: number };
type DragOperation = {
  kind: "move" | "resize";
  region: RegionView;
  startX: number;
  startY: number;
  initial: Box;
  pointerId: number;
};

type DrawOperation = { startX: number; startY: number; pointerId: number };

const READER_REGION_TYPES = new Set(["dialogue", "thought", "narration", "caption", "sign", "ui"]);

function regionBox(region: RegionView): Box {
  const points = region.geometry.filter((point) => point.length >= 2);
  if (!points.length) return { left: 0, top: 0, width: 24, height: 24 };
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  const left = Math.min(...xs);
  const top = Math.min(...ys);
  return {
    left,
    top,
    width: Math.max(Math.max(...xs) - left, 1),
    height: Math.max(Math.max(...ys) - top, 1)
  };
}

function geometryFromBox(box: Box): number[][] {
  return [
    [box.left, box.top],
    [box.left + box.width, box.top],
    [box.left + box.width, box.top + box.height],
    [box.left, box.top + box.height]
  ];
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function boxStyle(box: Box, page: PageView): CSSProperties {
  const width = page.width ?? 1;
  const height = page.height ?? 1;
  return {
    left: `${(box.left / width) * 100}%`,
    top: `${(box.top / height) * 100}%`,
    width: `${Math.max((box.width / width) * 100, 0.8)}%`,
    height: `${Math.max((box.height / height) * 100, 0.8)}%`
  };
}

function overlayStyle(region: RegionView, page: PageView, draft?: Box): CSSProperties {
  const rawFontSize = Number(region.localization?.layout?.fontSize ?? 24);
  const pageWidth = page.width ?? 1000;
  return {
    ...boxStyle(draft ?? regionBox(region), page),
    fontSize: `${(rawFontSize / pageWidth) * 100}cqw`,
    lineHeight: Number(region.localization?.layout?.lineHeight ?? 1.22)
  };
}

type MangaStageProps = {
  page: PageView;
  showOriginal?: boolean;
  interactive?: boolean;
  selectedRegionId?: number | null;
  drawMode?: boolean;
  onSelect?: (region: RegionView) => void;
  onGeometryChange?: (region: RegionView, geometry: number[][]) => Promise<void> | void;
  onCreateRegion?: (geometry: number[][]) => Promise<void> | void;
};

export function MangaStage({
  page,
  showOriginal = false,
  interactive = false,
  selectedRegionId,
  drawMode = false,
  onSelect,
  onGeometryChange,
  onCreateRegion
}: MangaStageProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<DragOperation | null>(null);
  const drawRef = useRef<DrawOperation | null>(null);
  const [draft, setDraft] = useState<{ regionId: number; box: Box } | null>(null);
  const [drawBox, setDrawBox] = useState<Box | null>(null);
  const image = showOriginal ? page.original_url : page.clean_url ?? page.original_url;
  const pageWidth = page.width ?? 1;
  const pageHeight = page.height ?? 1;

  const scaleDelta = (dx: number, dy: number) => {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect?.width || !rect.height) return { x: 0, y: 0 };
    return { x: dx * (pageWidth / rect.width), y: dy * (pageHeight / rect.height) };
  };

  const pagePoint = (clientX: number, clientY: number) => {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect?.width || !rect.height) return { x: 0, y: 0 };
    return {
      x: clamp((clientX - rect.left) * (pageWidth / rect.width), 0, pageWidth),
      y: clamp((clientY - rect.top) * (pageHeight / rect.height), 0, pageHeight)
    };
  };

  const startDrag = (event: PointerEvent<HTMLElement>, region: RegionView, kind: "move" | "resize") => {
    if (!interactive || !onGeometryChange) return;
    event.preventDefault();
    event.stopPropagation();
    onSelect?.(region);
    event.currentTarget.setPointerCapture(event.pointerId);
    const initial = draft?.regionId === region.id ? draft.box : regionBox(region);
    dragRef.current = { kind, region, startX: event.clientX, startY: event.clientY, initial, pointerId: event.pointerId };
    setDraft({ regionId: region.id, box: initial });
  };

  const updateDrag = (event: PointerEvent<HTMLElement>) => {
    const operation = dragRef.current;
    if (!operation || operation.pointerId !== event.pointerId) return;
    event.preventDefault();
    const delta = scaleDelta(event.clientX - operation.startX, event.clientY - operation.startY);
    let next: Box;
    if (operation.kind === "move") {
      next = {
        ...operation.initial,
        left: clamp(operation.initial.left + delta.x, 0, pageWidth - operation.initial.width),
        top: clamp(operation.initial.top + delta.y, 0, pageHeight - operation.initial.height)
      };
    } else {
      next = {
        ...operation.initial,
        width: clamp(operation.initial.width + delta.x, 12, pageWidth - operation.initial.left),
        height: clamp(operation.initial.height + delta.y, 12, pageHeight - operation.initial.top)
      };
    }
    setDraft({ regionId: operation.region.id, box: next });
  };

  const finishDrag = async (event: PointerEvent<HTMLElement>) => {
    const operation = dragRef.current;
    if (!operation || operation.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    const finalBox = draft?.regionId === operation.region.id ? draft.box : operation.initial;
    dragRef.current = null;
    setDraft(null);
    await onGeometryChange?.(operation.region, geometryFromBox(finalBox));
  };

  const startDraw = (event: PointerEvent<HTMLDivElement>) => {
    if (!interactive || !drawMode || !onCreateRegion) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = pagePoint(event.clientX, event.clientY);
    drawRef.current = { startX: point.x, startY: point.y, pointerId: event.pointerId };
    setDrawBox({ left: point.x, top: point.y, width: 1, height: 1 });
  };

  const updateDraw = (event: PointerEvent<HTMLDivElement>) => {
    const operation = drawRef.current;
    if (!operation || operation.pointerId !== event.pointerId) return;
    const point = pagePoint(event.clientX, event.clientY);
    setDrawBox({
      left: Math.min(operation.startX, point.x),
      top: Math.min(operation.startY, point.y),
      width: Math.abs(point.x - operation.startX),
      height: Math.abs(point.y - operation.startY)
    });
  };

  const finishDraw = async (event: PointerEvent<HTMLDivElement>) => {
    const operation = drawRef.current;
    if (!operation || operation.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    const finalBox = drawBox;
    drawRef.current = null;
    setDrawBox(null);
    if (finalBox && finalBox.width >= 12 && finalBox.height >= 12) {
      await onCreateRegion?.(geometryFromBox(finalBox));
    }
  };

  return (
    <div
      ref={stageRef}
      className={`manga-stage${drawMode ? " draw-mode" : ""}`}
      style={{ aspectRatio: `${pageWidth} / ${pageHeight}` }}
      onPointerDown={startDraw}
      onPointerMove={updateDraw}
      onPointerUp={finishDraw}
      onPointerCancel={finishDraw}
    >
      <img src={image} alt={`Page ${page.page_index}`} />
      {!showOriginal && page.regions.map((region) => {
        if (!interactive && !READER_REGION_TYPES.has(region.region_type)) return null;
        const text = region.localization?.text?.trim();
        if (!text && !interactive) return null;
        const lines = region.localization?.layout?.fittedLines;
        const display = Array.isArray(lines) && lines.length ? lines.join("\n") : text || region.source_text || "…";
        const selected = selectedRegionId === region.id;
        const className = [
          "region-overlay",
          interactive ? "interactive" : "reader-overlay",
          selected ? "selected" : "",
          !text ? "untranslated" : "",
          `region-${region.region_type}`
        ].filter(Boolean).join(" ");
        if (interactive) {
          return (
            <button
              key={region.id}
              className={className}
              style={overlayStyle(region, page, draft?.regionId === region.id ? draft.box : undefined)}
              onClick={(event) => { event.stopPropagation(); onSelect?.(region); }}
              onPointerDown={(event) => startDrag(event, region, "move")}
              onPointerMove={updateDrag}
              onPointerUp={finishDrag}
              onPointerCancel={finishDrag}
              title={`${region.region_type} · #${region.reading_order}`}
            >
              {display}
              {selected && onGeometryChange && (
                <span
                  className="resize-handle"
                  role="presentation"
                  onPointerDown={(event) => startDrag(event, region, "resize")}
                  onPointerMove={updateDrag}
                  onPointerUp={finishDrag}
                  onPointerCancel={finishDrag}
                />
              )}
            </button>
          );
        }
        return <div key={region.id} className={className} style={overlayStyle(region, page)}>{display}</div>;
      })}
      {drawBox && <div className="region-draw-preview" style={boxStyle(drawBox, page)} />}
    </div>
  );
}
