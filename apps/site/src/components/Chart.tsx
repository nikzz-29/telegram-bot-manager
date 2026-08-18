import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { formatDate, formatNumber, type Locale } from "../i18n";
import { getPointRadii, interpolateGeometry, toGeometry, type ChartMetric, type GeometryPoint } from "./chart/geometry";
import type { Point } from "../types";

const labels: Record<ChartMetric, string> = {
  messages: "Messages",
  active_users: "Active users",
  joins: "New members",
  moderation_actions: "Moderation",
};

type ChartProps = {
  series: Point[];
  metric: ChartMetric;
  total?: number;
  locale?: Locale;
  label?: string;
  emptyLabel?: string;
};

const geometryCount = (series: Point[]): number => Math.max(1, Math.min(48, series.length || 1));
const toSvg = (point: GeometryPoint): { x: number; y: number } => ({ x: 4 + point.x * 0.92, y: 8 + point.y * 0.72 });
const pointString = (points: GeometryPoint[]): string => points.map((point) => { const svg = toSvg(point); return `${svg.x.toFixed(2)},${svg.y.toFixed(2)}`; }).join(" ");
const areaString = (points: GeometryPoint[]): string => points.length ? `4,80 ${pointString(points)} 96,80` : "";

export function Chart({ series, metric, total, locale = "en", label = labels[metric], emptyLabel = "No activity for this period" }: ChartProps): React.JSX.Element {
  const target = useMemo(() => toGeometry(series, metric, geometryCount(series)), [metric, series]);
  const [geometry, setGeometry] = useState<GeometryPoint[]>(target);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const previous = useRef<GeometryPoint[]>(target);
  const firstRender = useRef(true);
  const animationFrame = useRef<number | null>(null);
  const reducedMotion = useRef(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [svgSize, setSvgSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    reducedMotion.current = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    return () => { if (animationFrame.current !== null) cancelAnimationFrame(animationFrame.current); };
  }, []);

  useLayoutEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const measure = () => {
      const { width, height } = svg.getBoundingClientRect();
      setSvgSize((previous) => previous.width === width && previous.height === height ? previous : { width, height });
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(svg);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const from = previous.current.length ? previous.current : target;
    previous.current = target;
    setActiveIndex(null);
    if (firstRender.current || reducedMotion.current || !from.length || !target.length) {
      firstRender.current = false;
      setGeometry(target);
      return;
    }
    if (animationFrame.current !== null) cancelAnimationFrame(animationFrame.current);
    const started = performance.now();
    const duration = 380;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setGeometry(interpolateGeometry(from, target, eased));
      if (progress < 1) animationFrame.current = requestAnimationFrame(tick);
      else animationFrame.current = null;
    };
    animationFrame.current = requestAnimationFrame(tick);
  }, [target]);

  const values = series.map((point) => point[metric]);
  const valueTotal = total ?? (metric === "active_users" ? Math.max(0, ...values) : values.reduce((sum, value) => sum + value, 0));
  const active = activeIndex === null ? null : geometry[Math.min(activeIndex, geometry.length - 1)];
  const activeSvg = active ? toSvg(active) : null;
  const tooltipLeft = activeSvg ? Math.max(8, Math.min(82, activeSvg.x - 10)) : 0;
  const tooltipTop = activeSvg ? Math.max(4, activeSvg.y - 25) : 0;

  function selectNearest(event: React.PointerEvent<SVGSVGElement>): void {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / Math.max(1, rect.width) * 100;
    const index = geometry.reduce((best, point, current) => Math.abs(point.x - x) < Math.abs(geometry[best].x - x) ? current : best, 0);
    setActiveIndex(index);
  }

  function handleKeyboard(event: React.KeyboardEvent<SVGEllipseElement>, index: number): void {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") { event.preventDefault(); setActiveIndex(Math.min(geometry.length - 1, index + 1)); }
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") { event.preventDefault(); setActiveIndex(Math.max(0, index - 1)); }
    if (event.key === "Escape") setActiveIndex(null);
  }

  return <div className="chart-wrap" aria-label={label}>
    <div className="chart-caption"><span>{label}</span><strong>{formatNumber(valueTotal, locale)}</strong></div>
    {series.length ? <div className="chart-visual">
      <svg ref={svgRef} viewBox="0 0 100 88" role="img" className={`line-chart ${firstRender.current ? "chart-first-draw" : ""}`} preserveAspectRatio="none" onPointerMove={selectNearest} onPointerLeave={() => setActiveIndex(null)}>
        <g className="chart-grid" aria-hidden="true">{[8, 44, 80].map((y) => <line key={y} x1="4" x2="96" y1={y} y2={y} vectorEffect="non-scaling-stroke" />)}</g>
        <polygon points={areaString(geometry)} className="chart-area" aria-hidden="true" />
        <polyline points={pointString(geometry)} className="chart-line" pathLength="1" vectorEffect="non-scaling-stroke" aria-hidden="true" />
        {geometry.map((point, index) => { const svg = toSvg(point); const source = series[Math.min(series.length - 1, Math.round(index / Math.max(1, geometry.length - 1) * (series.length - 1)))]; const radii = getPointRadii(activeIndex === index ? 2.8 : 1.7, svgSize.width, svgSize.height); return <ellipse key={index} cx={svg.x} cy={svg.y} rx={radii.rx} ry={radii.ry} className={`chart-point ${activeIndex === index ? "active" : ""}`} vectorEffect="non-scaling-stroke" tabIndex={0} role="button" aria-label={`${formatDate(source?.date ?? point.date, locale)}: ${formatNumber(source?.[metric] ?? point.value, locale)}`} onFocus={() => setActiveIndex(index)} onBlur={() => setActiveIndex(null)} onKeyDown={(event) => handleKeyboard(event, index)} onPointerMove={(event) => { event.stopPropagation(); setActiveIndex(index); }} onPointerDown={() => setActiveIndex(index)} />; })}
      </svg>
      <div className="chart-axis-labels" aria-hidden="true"><span>{series[0]?.date}</span><span>{series.at(-1)?.date}</span></div>
      {active && activeSvg && <div className="chart-tooltip" style={{ left: `${tooltipLeft}%`, top: `${tooltipTop}%` }} role="status"><b>{formatDate(active.date, locale)}</b><span>{label}</span><strong>{formatNumber(Math.round(active.value), locale)}</strong></div>}
    </div> : <div className="chart-empty">{emptyLabel}</div>}
  </div>;
}

export type { ChartMetric };
