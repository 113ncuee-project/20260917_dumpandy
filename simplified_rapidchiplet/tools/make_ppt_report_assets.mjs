import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const resultsDir = path.join(root, "results", "latest");
const outDir = path.join(resultsDir, "ppt_assets");

fs.mkdirSync(outDir, { recursive: true });

const summary = JSON.parse(fs.readFileSync(path.join(resultsDir, "pareto_dp", "balanced", "summary.json"), "utf8"));
const comparison = parseCsv(fs.readFileSync(path.join(resultsDir, "search_comparison_with_bonus.csv"), "utf8"));
const reportStat = fs.statSync(path.join(resultsDir, "report.html"));
const generatedAt = reportStat.mtime.toISOString().replace("T", " ").slice(0, 19);

const resnetBalanced = summary.find((row) => row.model === "resnet50" && row.topology === "mesh");
const resnetTree = summary.find((row) => row.model === "resnet50" && row.topology === "tree");
const shufflenetBalanced = summary.find((row) => row.model === "shufflenet_v2_x1_0" && row.topology === "mesh");
const resnetGoals = goalRows("resnet50");
const searchRows = makeSearchRows();

const pages = [
  {
    file: "01_latest_result_overview.html",
    title: "Latest Result Overview",
    body: overviewPage(),
  },
  {
    file: "02_resnet_goal_tradeoff.html",
    title: "ResNet50 Goal Trade-off",
    body: goalTradeoffPage(),
  },
  {
    file: "03_resnet_partition_mapping.html",
    title: "ResNet50 Partition Mapping",
    body: partitionPage(resnetBalanced),
  },
  {
    file: "04_resnet_topology_traffic.html",
    title: "ResNet50 Topology / Traffic",
    body: topologyPage(resnetBalanced, resnetTree),
  },
  {
    file: "05_search_method_check.html",
    title: "Search Method Check",
    body: searchMethodPage(),
  },
];

const manifest = [];
for (const page of pages) {
  const html = shell(page.title, page.body);
  const htmlPath = path.join(outDir, page.file);
  fs.writeFileSync(htmlPath, html, "utf8");
  manifest.push({
    title: page.title,
    html: htmlPath,
    png: htmlPath.replace(/\.html$/, ".png"),
  });
}

fs.writeFileSync(path.join(outDir, "manifest.json"), JSON.stringify(manifest, null, 2), "utf8");
console.log(`Wrote ${manifest.length} PPT-ready HTML assets to ${outDir}`);

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = splitCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const cells = splitCsvLine(line);
    return Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? ""]));
  });
}

function splitCsvLine(line) {
  const cells = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (quoted && line[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      cells.push(cell);
      cell = "";
    } else {
      cell += char;
    }
  }
  cells.push(cell);
  return cells;
}

function goalRows(model) {
  return ["balanced", "latency", "power", "area"].map((goal) =>
    comparison.find((row) => row.ppa_goal === goal && row.search === "pareto-dp" && row.model === model)
  ).filter(Boolean);
}

function makeSearchRows() {
  const goals = ["balanced", "latency", "power", "area"];
  const models = ["resnet50", "shufflenet_v2_x1_0"];
  return goals.flatMap((goal) => models.map((model) => {
    const brute = comparison.find((row) => row.ppa_goal === goal && row.search === "brute-force" && row.model === model);
    const dp = comparison.find((row) => row.ppa_goal === goal && row.search === "pareto-dp" && row.model === model);
    return {
      goal,
      model,
      brute,
      dp,
      sameMetrics: brute && dp && sameDesignMetrics(brute, dp),
    };
  })).filter((row) => row.brute && row.dp);
}

function sameDesignMetrics(left, right) {
  const keys = ["topology", "status", "used_chiplets", "achieved_fps", "area_mm2", "power_w", "latency_ns", "ppa_score"];
  return keys.every((key) => left[key] === right[key]);
}

function shell(title, body) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>${esc(title)}</title>
  <style>
    :root {
      --ink: #17202a;
      --muted: #5d6875;
      --line: #d8dee6;
      --soft: #f5f7fa;
      --blue: #2f6fad;
      --green: #117a65;
      --red: #a93226;
      --orange: #b86b1b;
      --purple: #7157a8;
      --shadow: rgba(18, 31, 45, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      width: 1600px;
      height: 900px;
      overflow: hidden;
      background: white;
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
    }
    .slide {
      width: 1600px;
      height: 900px;
      padding: 56px 70px 44px;
      display: flex;
      flex-direction: column;
      gap: 28px;
    }
    .topline {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 32px;
      border-bottom: 2px solid var(--line);
      padding-bottom: 18px;
    }
    h1 {
      margin: 0;
      font-size: 48px;
      line-height: 1.08;
      letter-spacing: 0;
      font-weight: 760;
    }
    .subtitle {
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 24px;
      line-height: 1.35;
    }
    .stamp {
      color: var(--muted);
      font-size: 18px;
      text-align: right;
      white-space: nowrap;
    }
    .grid-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 26px;
      min-height: 0;
    }
    .grid-3 {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 22px;
    }
    .panel {
      border: 1px solid var(--line);
      background: white;
      border-radius: 8px;
      box-shadow: 0 8px 24px var(--shadow);
      padding: 24px;
      min-width: 0;
    }
    .panel h2 {
      margin: 0 0 16px;
      font-size: 28px;
      line-height: 1.15;
      letter-spacing: 0;
    }
    .metric-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
    }
    .metric {
      border-left: 5px solid var(--blue);
      padding: 8px 12px 8px 16px;
      background: var(--soft);
      min-height: 112px;
    }
    .metric .label {
      color: var(--muted);
      font-size: 18px;
      margin-bottom: 8px;
    }
    .metric .value {
      font-size: 32px;
      font-weight: 760;
      line-height: 1.1;
    }
    .metric .note {
      color: var(--muted);
      font-size: 16px;
      margin-top: 6px;
      line-height: 1.25;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 20px;
    }
    th {
      color: #273442;
      background: #eef2f6;
      text-align: left;
      font-weight: 760;
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
    }
    td {
      padding: 13px 14px;
      border-bottom: 1px solid var(--line);
      vertical-align: middle;
    }
    tr:last-child td { border-bottom: 0; }
    .status {
      font-weight: 760;
    }
    .met { color: var(--green); }
    .miss { color: var(--red); }
    .bar-track {
      width: 100%;
      height: 14px;
      background: #e8edf3;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 7px;
    }
    .bar {
      height: 100%;
      border-radius: 999px;
      background: var(--blue);
    }
    .small {
      color: var(--muted);
      font-size: 16px;
      line-height: 1.35;
    }
    .claim {
      font-size: 31px;
      line-height: 1.25;
      font-weight: 730;
      margin: 0;
    }
    .callout {
      border-left: 6px solid var(--green);
      background: #eff8f4;
      padding: 20px 22px;
      font-size: 24px;
      line-height: 1.35;
    }
    .footer {
      margin-top: auto;
      color: var(--muted);
      font-size: 15px;
    }
    .chip-grid {
      display: grid;
      grid-template-columns: repeat(9, 1fr);
      gap: 11px;
    }
    .chiplet {
      border: 1px solid var(--line);
      border-top: 7px solid var(--blue);
      border-radius: 8px;
      background: #fbfcfd;
      min-height: 164px;
      padding: 12px;
    }
    .chiplet strong {
      display: block;
      font-size: 20px;
      margin-bottom: 8px;
    }
    .chiplet .stage {
      font-size: 18px;
      min-height: 48px;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }
    .chiplet .ops {
      color: var(--muted);
      font-size: 15px;
      margin-top: 10px;
    }
    svg { display: block; width: 100%; height: 100%; }
    .legend {
      display: flex;
      gap: 24px;
      align-items: center;
      color: var(--muted);
      font-size: 18px;
      margin-top: 10px;
    }
    .legend .sample {
      display: inline-block;
      width: 36px;
      height: 0;
      border-top: 4px solid var(--line);
      margin-right: 8px;
      vertical-align: middle;
    }
    .legend .traffic {
      border-top-style: dashed;
      border-color: var(--red);
    }
  </style>
</head>
<body>
${body}
</body>
</html>`;
}

function overviewPage() {
  return `<section class="slide">
    ${header("Simulation results are clearest as a decision story", "Show the best feasible design first, then use trade-offs to explain why it was selected.")}
    <div class="metric-row">
      ${metric("ResNet50 best", `${fmt(resnetBalanced.achieved_fps, 2)} FPS`, `${resnetBalanced.selected_chiplets}/${resnetBalanced.available_chiplets} chiplets, ${fmt(resnetBalanced.ppa_score, 3)} PPA score`, "var(--green)")}
      ${metric("ResNet50 package", `${fmt(resnetBalanced.total_area_mm2, 1)} mm^2`, `${fmt(resnetBalanced.total_power_w, 1)} W, ${fmt(resnetBalanced.avg_latency_ns, 1)} ns`, "var(--blue)")}
      ${metric("ShuffleNetV2 best", `${fmt(shufflenetBalanced.achieved_fps, 2)} FPS`, `single chiplet, ${fmt(shufflenetBalanced.ppa_score, 3)} PPA score`, "var(--purple)")}
      ${metric("Target", `${fmt(resnetBalanced.target_fps, 0)} FPS`, "balanced goal, Pareto-DP search", "var(--orange)")}
    </div>
    <div class="grid-2">
      <div class="panel">
        <h2>Balanced Pareto-DP winners</h2>
        <table>
          <thead><tr><th>Model</th><th>Topology</th><th>Status</th><th>FPS</th><th>Chiplets</th><th>PPA</th></tr></thead>
          <tbody>
            ${summary.map((row) => `<tr>
              <td>${esc(displayModel(row.model))}</td>
              <td>${esc(row.topology)}</td>
              <td class="status ${row.target_met ? "met" : "miss"}">${row.target_met ? "MET" : "MISS"}</td>
              <td>${fmt(row.achieved_fps, 2)}</td>
              <td>${row.selected_chiplets}/${row.available_chiplets}</td>
              <td>${fmt(row.ppa_score, 3)}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>
      <div class="panel">
        <h2>Presentation takeaway</h2>
        <p class="claim">Balanced objective selects mesh for ResNet50 because it meets 15 FPS with lower latency than tree, while ShuffleNetV2 is already satisfied by one chiplet.</p>
        <div class="callout" style="margin-top: 28px;">Use one slide for the conclusion, one slide for the PPA goal trade-off, and one slide for the chiplet mapping that explains where the design cost comes from.</div>
      </div>
    </div>
    ${footer()}
  </section>`;
}

function goalTradeoffPage() {
  const maxFps = Math.max(...resnetGoals.map((row) => number(row.achieved_fps)), 15);
  const maxArea = Math.max(...resnetGoals.map((row) => number(row.area_mm2)));
  const maxPower = Math.max(...resnetGoals.map((row) => number(row.power_w)));
  return `<section class="slide">
    ${header("PPA goals change the ResNet50 design choice", "Balanced and latency goals meet the 15 FPS target; power and area goals save resources but miss the target.")}
    <div class="panel" style="padding: 20px 24px;">
      <table>
        <thead><tr><th>Goal</th><th>Status</th><th>FPS</th><th>Chiplets</th><th>Area</th><th>Power</th><th>Latency</th><th>PPA score</th></tr></thead>
        <tbody>
          ${resnetGoals.map((row) => `<tr>
            <td>${goalName(row.ppa_goal)}</td>
            <td class="status ${row.status === "MET" ? "met" : "miss"}">${row.status}</td>
            <td>${fmt(row.achieved_fps, 2)}${bar(number(row.achieved_fps), maxFps, row.status === "MET" ? "var(--green)" : "var(--red)")}</td>
            <td>${row.used_chiplets}/16</td>
            <td>${fmt(row.area_mm2, 1)}${bar(number(row.area_mm2), maxArea, "var(--blue)")}</td>
            <td>${fmt(row.power_w, 1)}${bar(number(row.power_w), maxPower, "var(--orange)")}</td>
            <td>${fmt(row.latency_ns, 1)} ns</td>
            <td>${fmt(row.ppa_score, 3)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <div class="grid-3">
      <div class="panel">
        <h2>Feasible choice</h2>
        <p class="claim">Balanced / latency use 9 chiplets and achieve ${fmt(resnetGoals[0].achieved_fps, 2)} FPS.</p>
      </div>
      <div class="panel">
        <h2>Power choice</h2>
        <p class="claim">Power goal drops to 8 chiplets and ${fmt(resnetGoals[2].power_w, 1)} W, but misses by ${fmt(15 - number(resnetGoals[2].achieved_fps), 2)} FPS.</p>
      </div>
      <div class="panel">
        <h2>Area choice</h2>
        <p class="claim">Area goal uses 6 chiplets and ${fmt(resnetGoals[3].area_mm2, 1)} mm^2, but reaches only ${fmt(resnetGoals[3].achieved_fps, 2)} FPS.</p>
      </div>
    </div>
    ${footer()}
  </section>`;
}

function partitionPage(row) {
  const nodes = row.connection_graph.nodes;
  const maxOps = Math.max(...nodes.map((node) => node.ops));
  return `<section class="slide">
    ${header("ResNet50 mapping reveals the compute bottleneck", "The balanced design spreads heavier ResNet stages across 9 active chiplets while leaving 7 chiplets unused.")}
    <div class="chip-grid">
      ${nodes.map((node) => chiplet(node, maxOps)).join("")}
    </div>
    <div class="grid-3">
      ${metric("Workload traffic", `${fmt(row.total_traffic_mb_per_inference, 2)} MB`, "per inference", "var(--red)")}
      ${metric("Bottleneck link", row.bottleneck_link, `${fmt(row.aggregate_throughput_bits_per_cycle, 1)} bits/cycle aggregate`, "var(--orange)")}
      ${metric("Compute vs network", `${fmt(row.compute_limited_fps, 2)} / ${fmt(row.network_limited_fps, 0)}`, "compute FPS / network FPS", "var(--blue)")}
    </div>
    ${footer()}
  </section>`;
}

function topologyPage(meshRow, treeRow) {
  return `<section class="slide">
    ${header("Mesh keeps ResNet50 latency lower than tree at the same chiplet count", "Both balanced topologies meet the target, but mesh has shorter communication latency in the reported configuration.")}
    <div class="grid-2" style="height: 560px;">
      <div class="panel">
        <h2>Mesh: ${fmt(meshRow.avg_latency_ns, 1)} ns, ${fmt(meshRow.total_power_w, 1)} W</h2>
        <div style="height: 410px;">${topologySvg(meshRow)}</div>
        <div class="legend"><span><span class="sample"></span>topology link</span><span><span class="sample traffic"></span>traffic path</span></div>
      </div>
      <div class="panel">
        <h2>Tree: ${fmt(treeRow.avg_latency_ns, 1)} ns, ${fmt(treeRow.total_power_w, 1)} W</h2>
        <div style="height: 410px;">${topologySvg(treeRow)}</div>
        <div class="legend"><span><span class="sample"></span>topology link</span><span><span class="sample traffic"></span>traffic path</span></div>
      </div>
    </div>
    <div class="callout">For the presentation, use mesh as the main result and mention tree only as a topology comparison: same 9 chiplets, similar FPS, but higher latency.</div>
    ${footer()}
  </section>`;
}

function searchMethodPage() {
  const matches = searchRows.filter((row) => row.sameMetrics).length;
  return `<section class="slide">
    ${header("Pareto-DP preserves the reported best designs", "Across goals and models, Pareto-DP matches brute-force on the selected metrics in the latest comparison report.")}
    <div class="metric-row">
      ${metric("Checks passed", `${matches}/${searchRows.length}`, "same topology, status, chiplets, FPS, area, power, latency, score", "var(--green)")}
      ${metric("Models", "2", "ResNet50 and ShuffleNetV2", "var(--blue)")}
      ${metric("Goals", "4", "balanced, latency, power, area", "var(--purple)")}
      ${metric("Use in talk", "Validation", "DP is not changing the reported optimum", "var(--orange)")}
    </div>
    <div class="panel">
      <table>
        <thead><tr><th>Goal</th><th>Model</th><th>Brute-force</th><th>Pareto-DP</th><th>Metric match</th></tr></thead>
        <tbody>
          ${searchRows.map((row) => `<tr>
            <td>${goalName(row.goal)}</td>
            <td>${esc(displayModel(row.model))}</td>
            <td>${row.brute.status}, ${row.brute.used_chiplets} chiplets, ${fmt(row.brute.achieved_fps, 2)} FPS</td>
            <td>${row.dp.status}, ${row.dp.used_chiplets} chiplets, ${fmt(row.dp.achieved_fps, 2)} FPS</td>
            <td class="status ${row.sameMetrics ? "met" : "miss"}">${row.sameMetrics ? "same" : "different"}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
    ${footer()}
  </section>`;
}

function header(title, subtitle) {
  return `<div class="topline">
    <div>
      <h1>${esc(title)}</h1>
      <p class="subtitle">${esc(subtitle)}</p>
    </div>
    <div class="stamp">latest report<br>${esc(generatedAt)}</div>
  </div>`;
}

function footer() {
  return `<div class="footer">Source: simplified_rapidchiplet/results/latest/report.html and search_comparison_with_bonus.csv</div>`;
}

function metric(label, value, note, color) {
  return `<div class="metric" style="border-left-color: ${color};">
    <div class="label">${esc(label)}</div>
    <div class="value">${esc(String(value))}</div>
    <div class="note">${esc(note)}</div>
  </div>`;
}

function bar(value, max, color) {
  const pct = max > 0 ? Math.max(1, Math.min(100, value / max * 100)) : 0;
  return `<div class="bar-track"><div class="bar" style="width: ${pct.toFixed(1)}%; background: ${color};"></div></div>`;
}

function chiplet(node, maxOps) {
  const color = stageColor(node.stage);
  return `<div class="chiplet" style="border-top-color: ${color};">
    <strong>C${node.id + 1}</strong>
    <div class="stage">${esc(node.stage)}</div>
    <div class="ops">${fmt(node.ops / 1e9, 2)} GOP / inference</div>
    ${bar(node.ops, maxOps, color)}
  </div>`;
}

function topologySvg(row) {
  const graph = row.connection_graph;
  const nodes = graph.nodes;
  const links = graph.physical_links;
  const traffic = graph.traffic_edges;
  const positions = row.topology === "tree"
    ? treePositions(nodes, links)
    : scaledPositions(nodes);
  const maxTraffic = Math.max(...traffic.map((edge) => edge.mb), 1);
  const physical = links.map((link) => line(positions[link.source], positions[link.target], "#98a6b5", 4, "none")).join("");
  const trafficPaths = traffic.map((edge) => {
    const a = positions[edge.source];
    const b = positions[edge.target];
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2 - 24;
    const width = 3 + 6 * edge.mb / maxTraffic;
    return `<path d="M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}" fill="none" stroke="#a93226" stroke-width="${width.toFixed(1)}" stroke-dasharray="12 8" marker-end="url(#arrow-${row.topology})"/>`;
  }).join("");
  const nodeMarkup = nodes.map((node) => {
    const p = positions[node.id];
    return `<g>
      <rect x="${p.x - 28}" y="${p.y - 28}" width="56" height="56" rx="7" fill="#e8f2ff" stroke="#2f6fad" stroke-width="3"/>
      <text x="${p.x}" y="${p.y + 2}" text-anchor="middle" dominant-baseline="middle" font-size="18" font-weight="700" fill="#17202a">C${node.id + 1}</text>
      <text x="${p.x}" y="${p.y + 48}" text-anchor="middle" font-size="14" fill="#5d6875">${esc(shortStage(node.stage))}</text>
    </g>`;
  }).join("");
  return `<svg viewBox="0 0 700 390" aria-label="${esc(row.model)} ${esc(row.topology)} topology">
    <defs>
      <marker id="arrow-${row.topology}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#a93226"></path>
      </marker>
    </defs>
    ${physical}
    ${trafficPaths}
    ${nodeMarkup}
  </svg>`;
}

function scaledPositions(nodes) {
  const xs = nodes.map((node) => node.x);
  const ys = nodes.map((node) => node.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const margin = 70;
  const width = 700;
  const height = 390;
  return Object.fromEntries(nodes.map((node) => [
    node.id,
    {
      x: maxX === minX ? width / 2 : margin + (node.x - minX) / (maxX - minX) * (width - margin * 2),
      y: maxY === minY ? height / 2 : margin + (node.y - minY) / (maxY - minY) * (height - margin * 2),
    },
  ]));
}

function treePositions(nodes, links) {
  const ids = nodes.map((node) => node.id).sort((a, b) => a - b);
  const root = ids[0];
  const adj = Object.fromEntries(ids.map((id) => [id, []]));
  for (const link of links) {
    adj[link.source]?.push(link.target);
    adj[link.target]?.push(link.source);
  }
  for (const id of ids) adj[id].sort((a, b) => a - b);
  const children = Object.fromEntries(ids.map((id) => [id, []]));
  const depth = { [root]: 0 };
  const parent = { [root]: -1 };
  const queue = [root];
  for (const id of queue) {
    for (const next of adj[id]) {
      if (parent[next] !== undefined) continue;
      parent[next] = id;
      depth[next] = depth[id] + 1;
      children[id].push(next);
      queue.push(next);
    }
  }
  let slot = 0;
  const slots = {};
  const assign = (id) => {
    if (!children[id].length) {
      slots[id] = slot;
      slot += 1;
      return slots[id];
    }
    const childSlots = children[id].map(assign);
    slots[id] = childSlots.reduce((a, b) => a + b, 0) / childSlots.length;
    return slots[id];
  };
  assign(root);
  const maxSlot = Math.max(...Object.values(slots), 1);
  const maxDepth = Math.max(...Object.values(depth), 1);
  const margin = 70;
  return Object.fromEntries(ids.map((id) => [
    id,
    {
      x: margin + slots[id] / maxSlot * (700 - margin * 2),
      y: margin + depth[id] / maxDepth * (390 - margin * 2),
    },
  ]));
}

function line(a, b, color, width, dash) {
  const dashAttr = dash === "none" ? "" : ` stroke-dasharray="${dash}"`;
  return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${color}" stroke-width="${width}"${dashAttr}/>`;
}

function number(value) {
  return Number.parseFloat(value);
}

function fmt(value, decimals) {
  const num = typeof value === "number" ? value : number(value);
  if (!Number.isFinite(num)) return "inf";
  return num.toFixed(decimals);
}

function goalName(goal) {
  return {
    balanced: "Balanced",
    latency: "Low latency",
    power: "Low power",
    area: "Low area",
  }[goal] ?? goal;
}

function displayModel(model) {
  return model === "shufflenet_v2_x1_0" ? "ShuffleNetV2" : model === "resnet50" ? "ResNet50" : model;
}

function shortStage(value) {
  return value.length > 16 ? `${value.slice(0, 13)}...` : value;
}

function stageColor(stage) {
  if (stage.startsWith("conv")) return "#2f6fad";
  if (stage.startsWith("layer1")) return "#117a65";
  if (stage.startsWith("layer2")) return "#b86b1b";
  if (stage.startsWith("layer3")) return "#7157a8";
  if (stage.startsWith("layer4")) return "#a93226";
  return "#4d7f87";
}

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
