// Figure rendering for the writeup. Data comes from site/data/*.json (scripts/export_writeup_data.py).
import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";

const css = getComputedStyle(document.documentElement);
const SPLITS = ["oneoff", "conflicting"];
const COLORS = SPLITS.map((s) => css.getPropertyValue(`--${s}`).trim());
const LABEL = { oneoff: "one-off", conflicting: "conflicting" };
const pct = (x) => `${(100 * x).toFixed(1)}%`;

const load = (name) => fetch(`data/${name}.json`).then((r) => r.json());

/** Render a Plot into a container, re-rendering at the container's width on resize. */
function mount(el, build) {
  const draw = () => el.replaceChildren(build(el.clientWidth));
  draw();
  new ResizeObserver(draw).observe(el);
  return draw;
}

async function byAttempt() {
  const data = await load("phase1_by_attempt");
  const el = document.getElementById("chart-by-attempt");
  const ci = document.getElementById("by-attempt-ci");
  const redraw = mount(el, (width) =>
    Plot.plot({
      width,
      height: 320,
      marginLeft: 48,
      x: { label: "attempt", ticks: 8, tickFormat: "d", domain: [1, 8] },
      y: { label: "cumulative cheat rate (%)", domain: [0, 100], percent: true, grid: true },
      color: { domain: SPLITS, range: COLORS, legend: true, tickFormat: (s) => LABEL[s] },
      marks: [
        ci.checked
          ? Plot.areaY(data, { x: "attempt", y1: "lo", y2: "hi", fill: "split", fillOpacity: 0.15 })
          : null,
        Plot.line(data, { x: "attempt", y: "rate", stroke: "split", strokeWidth: 2 }),
        Plot.dot(data, { x: "attempt", y: "rate", fill: "split", r: 3 }),
        Plot.tip(
          data,
          Plot.pointer({
            x: "attempt",
            y: "rate",
            title: (d) =>
              `${LABEL[d.split]}, by attempt ${d.attempt}\n${pct(d.rate)} (95% CI ${pct(d.lo)}–${pct(d.hi)})`,
          })
        ),
      ],
    })
  );
  ci.addEventListener("change", redraw);
}

async function byTask() {
  const rows = await load("phase1_by_task");
  const tasks = {};
  for (const r of rows) (tasks[r.task] ??= {})[r.split] = r.cheats;
  const counts = {};
  for (const t of Object.values(tasks)) {
    const key = `${t.oneoff}-${t.conflicting}`;
    counts[key] = (counts[key] ?? 0) + 1;
  }
  const cells = Object.entries(counts).map(([k, n]) => {
    const [oneoff, conflicting] = k.split("-").map(Number);
    return { oneoff, conflicting, n };
  });
  const el = document.getElementById("chart-by-task");
  mount(el, (width) =>
    Plot.plot({
      width: Math.min(width, 420),
      height: 340,
      marginLeft: 60,
      marginBottom: 44,
      x: { label: "one-off samples cheated (of 2)", domain: [0, 1, 2], type: "point", inset: 30 },
      y: { label: "conflicting samples cheated (of 2)", domain: [2, 1, 0], type: "point", inset: 30 },
      r: { range: [0, 34] },
      marks: [
        Plot.dot(cells, {
          x: "oneoff",
          y: "conflicting",
          r: "n",
          fill: "var(--conflicting)",
          fillOpacity: 0.5,
          stroke: "var(--conflicting)",
          tip: true,
          title: (d) => `${d.n} problems\none-off ${d.oneoff}/2, conflicting ${d.conflicting}/2`,
        }),
        Plot.text(cells, { x: "oneoff", y: "conflicting", text: "n", fontSize: 11, fill: "black" }),
      ],
    })
  );
}

byAttempt();
byTask();
