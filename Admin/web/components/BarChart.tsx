import type { Point } from "@/lib/api";

export function BarChart({ title, points }: { title: string; points: Point[] }) {
  const total = points.reduce((sum, p) => sum + p.count, 0);
  const max = Math.max(1, ...points.map((p) => p.count));
  const gap = 2;
  const width = 300;
  const bar = (width - gap * (points.length - 1)) / points.length;
  return (
    <figure className="card chart" style={{ margin: 0 }}>
      <figcaption>
        <span className="label">{title}</span>
        <span className="sub"> · {total} in 30 days</span>
      </figcaption>
      <svg viewBox={`0 0 ${width} 100`} preserveAspectRatio="none" role="img" aria-label={`${title}: ${total} in the last 30 days`}>
        {points.map((p, i) => {
          const h = p.count === 0 ? 1 : Math.max(2, (p.count / max) * 98);
          return (
            <rect key={p.date} x={i * (bar + gap)} y={100 - h} width={bar} height={h} rx={1} opacity={p.count === 0 ? 0.25 : 1}>
              <title>{`${p.date}: ${p.count}`}</title>
            </rect>
          );
        })}
      </svg>
      <p className="muted" style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
        <span>{points[0]?.date}</span>
        <span>peak {max === 1 && total === 0 ? 0 : max}</span>
        <span>{points[points.length - 1]?.date}</span>
      </p>
    </figure>
  );
}
