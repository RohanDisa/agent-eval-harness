"""Self-contained HTML span-tree viewer. No framework, no external assets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aeh.grading.tier2_golden import parse_divergence
from aeh.metrics.cost import estimate_cost
from aeh.models import RunResult, Trace


def _divergence_step(result: RunResult) -> int | None:
    for grade in result.grades:
        parsed = parse_divergence(grade)
        if parsed and parsed.get("divergence_step") is not None:
            return int(parsed["divergence_step"])
    return None


def _nodes_from_trace(trace: Trace) -> list[dict[str, Any]]:
    tree = trace.span_tree or trace.ensure_spans()
    by_span: dict[str, dict[str, Any]] = {}
    for step in trace.steps:
        sid = step.span_id or f"step-{step.index}"
        by_span[sid] = {
            "kind": "step",
            "name": f"step-{step.index}",
            "index": step.index,
            "latency_ms": step.model_latency_ms,
            "tokens": step.model_input_tokens + step.model_output_tokens,
            "cost": estimate_cost(trace.model, step.model_input_tokens, step.model_output_tokens),
            "reasoning": step.reasoning_text or "",
            "raw": step.raw_response,
            "error": None,
            "injected_fault": None,
            "passed": None,
        }
        if step.tool_call:
            tc = step.tool_call
            tid = tc.span_id or f"tool-{step.index}"
            by_span[tid] = {
                "kind": "tool",
                "name": tc.name,
                "index": tc.index,
                "latency_ms": tc.latency_ms,
                "tokens": 0,
                "cost": 0.0,
                "args": tc.arguments,
                "result": tc.result or "",
                "error": tc.error,
                "injected_fault": tc.injected_fault,
                "passed": False if tc.error else True,
            }
    return _enrich(tree, by_span)


def _enrich(nodes: list[dict[str, Any]], extra: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes:
        merged = {**node, **extra.get(node.get("span_id", ""), {})}
        merged["children"] = _enrich(node.get("children") or [], extra)
        out.append(merged)
    return out


def render_trace_tree(result: RunResult, out_path: Path | None = None) -> str:
    trace = result.trace
    nodes = _nodes_from_trace(trace)
    diverge = _divergence_step(result)
    payload = json.dumps(
        {
            "run_id": trace.run_id,
            "task_id": trace.task_id,
            "attempt": trace.attempt,
            "success": result.success,
            "needs_human_review": result.needs_human_review,
            "divergence_step": diverge,
            "final_output": trace.final_output,
            "nodes": nodes,
        },
        default=str,
    )
    page = _PAGE.replace("__PAYLOAD__", payload.replace("</", "<\\/"))
    if out_path:
        out_path.write_text(page, encoding="utf-8")
    return page


_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Agent Eval Harness</title>
<style>
  html, body { height: 100%; margin: 0; }
  body {
    font: 13px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: #1b1f24; color: #e8e4dc;
    display: flex; flex-direction: column;
  }
  header {
    padding: 0.7rem 1rem 0.4rem;
    border-bottom: 1px solid #3a414a;
    flex: 0 0 auto;
  }
  h1 { font-size: 13px; margin: 0 0 0.2rem; font-weight: 700; }
  .muted { color: #8b939e; }
  #stage {
    flex: 1 1 auto;
    position: relative;
    overflow: hidden;
  }
  svg { width: 100%; height: 100%; display: block; }
  .edge { fill: none; stroke: #7d8794; stroke-width: 1.6; }
  .edge.on { stroke: #d8c38a; }
  .node { cursor: pointer; }
  .node rect {
    fill: #2a3038; stroke: #6d7682; stroke-width: 1.2;
  }
  .node:hover rect { stroke: #e8e4dc; }
  .node.selected rect { stroke: #d8c38a; stroke-width: 2; fill: #353c46; }
  .node.diverge rect { fill: #4a2a2a; stroke: #d46a6a; stroke-width: 2; }
  .node.has-kids rect { stroke-dasharray: none; }
  .label { fill: #e8e4dc; font: 12px ui-monospace, Menlo, Consolas, monospace; pointer-events: none; }
  .sub { fill: #9aa3ad; font: 10px ui-monospace, Menlo, Consolas, monospace; pointer-events: none; }
  .hint { fill: #d8c38a; font: 10px ui-monospace, Menlo, Consolas, monospace; pointer-events: none; }
  #panel {
    flex: 0 0 auto;
    max-height: 34%;
    overflow: auto;
    border-top: 1px solid #3a414a;
    background: #14181d;
    padding: 0.7rem 1rem 1rem;
    white-space: pre-wrap;
    display: none;
  }
  #panel.open { display: block; }
  .badge { display: inline-block; padding: 0 0.35rem; border: 1px solid #6d7682; }
  .ok { color: #7dcea0; border-color: #7dcea0; }
  .fail { color: #e07a7a; border-color: #e07a7a; }
  .fault { color: #e0b15a; border-color: #e0b15a; }
</style>
</head>
<body>
<header>
  <h1>Agent Eval Harness</h1>
  <p class="muted" id="meta"></p>
  <p class="muted">Click a node to draw arrows to its children. Click a child to inspect it. Click again to collapse.</p>
</header>
<div id="stage"><svg id="graph"></svg></div>
<pre id="panel"></pre>
<script>
const DATA = __PAYLOAD__;
const NW = 168, NH = 58, GAP = 28, VGAP = 86;
const expanded = new Set();
let selected = null;

document.getElementById('meta').textContent =
  DATA.run_id + ' · ' + DATA.task_id + '#' + DATA.attempt +
  ' · ' + (DATA.success ? 'pass' : 'fail') +
  (DATA.needs_human_review ? ' · needs review' : '');

const root = {
  span_id: 'root',
  kind: 'trace',
  name: DATA.task_id,
  index: -1,
  children: DATA.nodes || [],
  latency_ms: 0,
  tokens: 0,
  cost: 0
};

function walk(node, fn) {
  fn(node);
  (node.children || []).forEach(c => walk(c, fn));
}
function visibleKids(node) {
  return expanded.has(node.span_id) ? (node.children || []) : [];
}
function isDiverge(node) {
  return DATA.divergence_step !== null && node.index === DATA.divergence_step;
}
function status(node) {
  if (node.injected_fault) return 'fault:' + node.injected_fault;
  if (node.passed === false || node.error) return 'fail';
  if (node.passed === true) return 'ok';
  return node.kind || 'step';
}
function detail(node) {
  const bits = [
    '[' + (node.kind || 'step') + '] ' + (node.name || ''),
    'latency ' + Number(node.latency_ms || 0).toFixed(0) + 'ms · ' +
      (node.tokens || 0) + ' tok · $' + Number(node.cost || 0).toFixed(6)
  ];
  if (node.injected_fault) bits.push('injected fault: ' + node.injected_fault);
  if (node.reasoning) bits.push('reasoning:\n' + node.reasoning);
  if (node.args) bits.push('args:\n' + JSON.stringify(node.args, null, 2));
  if (node.result) bits.push('result:\n' + node.result);
  if (node.error) bits.push('error:\n' + node.error);
  if (node.span_id === 'root' && DATA.final_output) bits.push('final output:\n' + DATA.final_output);
  return bits.join('\n\n');
}

function layout(node, depth, left) {
  const kids = visibleKids(node);
  if (!kids.length) {
    node._w = NW + GAP;
    node._x = left + node._w / 2;
    node._y = 36 + depth * (NH + VGAP);
    return node._w;
  }
  let acc = 0;
  kids.forEach(k => { acc += layout(k, depth + 1, left + acc); });
  node._w = Math.max(NW + GAP, acc);
  node._x = left + node._w / 2;
  node._y = 36 + depth * (NH + VGAP);
  return node._w;
}

function draw() {
  const svg = document.getElementById('graph');
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const defs = el(svg, 'defs', {});
  const mark = el(defs, 'marker', {
    id: 'arrow', viewBox: '0 0 10 10', refX: '9', refY: '5',
    markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse'
  });
  el(mark, 'path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: '#d8c38a' });

  const treeW = layout(root, 0, 0);
  const box = svg.getBoundingClientRect();
  const shiftX = Math.max(24, (box.width - treeW) / 2);
  walk(root, n => { n._x += shiftX; });

  const edges = el(svg, 'g', {});
  const nodes = el(svg, 'g', {});
  paint(root, edges, nodes);
}

function paint(node, edges, nodes) {
  const kids = visibleKids(node);
  kids.forEach(child => {
    const x1 = node._x, y1 = node._y + NH;
    const x2 = child._x, y2 = child._y;
    const mid = (y1 + y2) / 2;
    el(edges, 'path', {
      d: 'M ' + x1 + ' ' + y1 + ' C ' + x1 + ' ' + mid + ' ' + x2 + ' ' + mid + ' ' + x2 + ' ' + y2,
      "class": 'edge on',
      'marker-end': 'url(#arrow)'
    });
    paint(child, edges, nodes);
  });
  const g = el(nodes, 'g', {
    "class": 'node' + (selected === node.span_id ? ' selected' : '') +
      (isDiverge(node) ? ' diverge' : '') +
      ((node.children || []).length ? ' has-kids' : ''),
    transform: 'translate(' + (node._x - NW / 2) + ',' + node._y + ')'
  });
  el(g, 'rect', { width: NW, height: NH, rx: 8, ry: 8 });
  el(g, 'text', { "class": 'label', x: 10, y: 18 }).textContent =
    (node.kind || 'step') + '  ' + (node.name || '');
  el(g, 'text', { "class": 'sub', x: 10, y: 34 }).textContent =
    Number(node.latency_ms || 0).toFixed(0) + 'ms  ' +
    (node.tokens || 0) + 'tok  $' + Number(node.cost || 0).toFixed(4) +
    '  ' + status(node);
  const nKids = (node.children || []).length;
  if (nKids && !expanded.has(node.span_id)) {
    el(g, 'text', { "class": 'hint', x: 10, y: 50 }).textContent =
      'click to expand ' + nKids + (nKids === 1 ? ' child' : ' children');
  } else if (nKids) {
    el(g, 'text', { "class": 'hint', x: 10, y: 50 }).textContent = 'click to collapse';
  }
  g.addEventListener('click', (ev) => {
    ev.stopPropagation();
    const has = (node.children || []).length;
    if (has) expanded.has(node.span_id) ? expanded.delete(node.span_id) : expanded.add(node.span_id);
    selected = node.span_id;
    const panel = document.getElementById('panel');
    panel.textContent = detail(node);
    panel.classList.toggle('open', true);
    draw();
  });
}

function el(parent, tag, attrs) {
  const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
  parent.appendChild(n);
  return n;
}

window.addEventListener('resize', draw);
draw();
</script>
</body>
</html>
"""
