import type { ReactElement } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartArtifact } from "../api/types";
import { formatCell, formatNumber } from "../lib/format";

// Categorical palette, ordered so adjacent series stay distinguishable for common colour-vision deficiencies.
export const SERIES = ["#3a63c8", "#3b8b6e", "#c9922e", "#8a4f7d", "#5b6b7f", "#b5523b", "#2f8fa3", "#7d7a2f"];

const axisTick = { fontSize: 12, fill: "var(--ink-3)" };
const tooltipStyle = {
  contentStyle: { borderRadius: 6, border: "1px solid var(--line)", fontSize: 13, boxShadow: "none" },
  formatter: (v: unknown) => formatNumber(v),
  labelFormatter: (l: unknown) => formatCell(l),
};

export function ChartView({ chart }: { chart: ChartArtifact }) {
  const { chart_type, data, x, y } = chart;
  const many = y.length > 1;
  const xTick = { ...axisTick, tickFormatter: (v: unknown) => formatCell(v) };
  const yAxis = (
    <YAxis tick={axisTick} tickFormatter={(v) => formatNumber(v, "compact")} width={56} axisLine={false} tickLine={false} />
  );
  const grid = <CartesianGrid stroke="var(--line)" vertical={false} />;

  let body: ReactElement;
  if (chart_type === "pie") {
    body = (
      <PieChart>
        <Pie isAnimationActive={false} data={data} dataKey={y[0]} nameKey={x} innerRadius="45%" outerRadius="80%" paddingAngle={1}
             stroke="var(--surface)">
          {data.map((_, i) => (
            <Cell key={i} fill={SERIES[i % SERIES.length]} />
          ))}
        </Pie>
        <Tooltip {...tooltipStyle} />
        <Legend iconType="square" wrapperStyle={{ fontSize: 13 }} />
      </PieChart>
    );
  } else if (chart_type === "scatter") {
    body = (
      <ScatterChart>
        {grid}
        <XAxis dataKey={x} type="number" name={x} tick={axisTick} tickFormatter={(v) => formatNumber(v, "compact")} />
        <YAxis dataKey={y[0]} type="number" name={y[0]} tick={axisTick} width={56}
               tickFormatter={(v) => formatNumber(v, "compact")} />
        <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
        <Scatter isAnimationActive={false} data={data} fill={SERIES[0]} fillOpacity={0.7} />
      </ScatterChart>
    );
  } else if (chart.band) {
    // Forecast: actuals, projection and an uncertainty band.
    const banded = data.map((d) => ({
      ...d,
      range: d[chart.band![0]] != null ? [d[chart.band![0]], d[chart.band![1]]] : undefined,
    }));
    body = (
      <ComposedChart data={banded}>
        {grid}
        <XAxis dataKey={x} tick={xTick} />
        {yAxis}
        <Tooltip {...tooltipStyle} />
        <Area dataKey="range" isAnimationActive={false} stroke="none" fill={SERIES[1]} fillOpacity={0.15} name="Likely range" />
        <Line dataKey="actual" isAnimationActive={false} stroke={SERIES[0]} strokeWidth={2} dot={false} name="Actual" />
        <Line dataKey="forecast" isAnimationActive={false} stroke={SERIES[1]} strokeWidth={2} strokeDasharray="5 4" dot={false} name="Forecast" />
        <Legend iconType="plainline" wrapperStyle={{ fontSize: 13 }} />
      </ComposedChart>
    );
  } else if (chart_type === "line" || chart_type === "area") {
    const Chart = chart_type === "line" ? LineChart : AreaChart;
    body = (
      <Chart data={data}>
        {grid}
        <XAxis dataKey={x} tick={xTick} minTickGap={24} />
        {yAxis}
        <Tooltip {...tooltipStyle} />
        {y.map((key, i) =>
          chart_type === "line" ? (
            <Line key={key} isAnimationActive={false} dataKey={key} stroke={SERIES[i % SERIES.length]} strokeWidth={2} dot={!many && data.length < 30} />
          ) : (
            <Area key={key} isAnimationActive={false} dataKey={key} stroke={SERIES[i % SERIES.length]} fill={SERIES[i % SERIES.length]}
                  fillOpacity={0.18} stackId={many ? "s" : undefined} />
          ),
        )}
        {many && <Legend iconType="plainline" wrapperStyle={{ fontSize: 13 }} />}
      </Chart>
    );
  } else {
    const horizontal = chart_type === "horizontal_bar";
    const stacked = chart_type === "stacked_bar";
    body = (
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} barCategoryGap="22%">
        <CartesianGrid stroke="var(--line)" horizontal={!horizontal} vertical={horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" tick={axisTick} tickFormatter={(v) => formatNumber(v, "compact")} axisLine={false} />
            <YAxis type="category" dataKey={x} tick={xTick} width={120} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} tick={xTick} interval="preserveStartEnd" />
            {yAxis}
          </>
        )}
        <Tooltip {...tooltipStyle} cursor={{ fill: "var(--wash)" }} />
        {y.map((key, i) => (
          <Bar key={key} isAnimationActive={false} dataKey={key} fill={SERIES[i % SERIES.length]} radius={stacked ? 0 : [3, 3, 0, 0]}
               stackId={stacked ? "s" : undefined} maxBarSize={56} />
        ))}
        {many && <Legend iconType="square" wrapperStyle={{ fontSize: 13 }} />}
      </BarChart>
    );
  }

  const height = chart_type === "horizontal_bar" ? Math.max(220, data.length * 30 + 40) : 300;
  return (
    <figure className="chart">
      <figcaption>
        {chart.title}
        {chart.note && <span className="chart-note">{chart.note}</span>}
      </figcaption>
      <div style={{ height }} role="img" aria-label={`${chart_type} chart: ${chart.title}`}>
        <ResponsiveContainer width="100%" height="100%">
          {body}
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
