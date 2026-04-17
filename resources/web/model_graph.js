/**
 * 系统模型关系图：与 entity_graph.build_entity_graph_payload 一致的边规则，
 * 力导向布局（无外部依赖）+ SVG 渲染。
 */

function buildGraphFromSystemModel(model) {
    const nodesById = new Map();
    const ensureNode = (name) => {
        const n = String(name || '').trim();
        if (!n) return;
        const id = `var:${n}`;
        if (!nodesById.has(id)) {
            nodesById.set(id, { id, label: n });
        }
    };

    (model && model.variables ? model.variables : []).forEach((v) => {
        ensureNode(v && v.name);
    });

    const links = [];
    let ei = 0;
    (model && model.relations ? model.relations : []).forEach((rel) => {
        const effect = String((rel && rel.effect_var) || '').trim();
        const causes = Array.isArray(rel && rel.cause_vars)
            ? rel.cause_vars.map((c) => String(c).trim()).filter(Boolean)
            : [];
        if (!effect || !causes.length) return;
        ensureNode(effect);
        causes.forEach((c) => {
            ensureNode(c);
            const src = `var:${c}`;
            const tgt = `var:${effect}`;
            links.push({ id: `edge_${ei}`, source: src, target: tgt });
            ei += 1;
        });
    });

    return { nodes: Array.from(nodesById.values()), links };
}

/**
 * 简化的力导向迭代：斥力 + 弹簧（边）+ 向心力。
 */
function runForceLayout(nodes, links, width, height, iterations) {
    const pos = new Map();
    const cx = width / 2;
    const cy = height / 2;
    nodes.forEach((n) => {
        pos.set(n.id, {
            x: cx + (Math.random() - 0.5) * width * 0.35,
            y: cy + (Math.random() - 0.5) * height * 0.35,
        });
    });

    const kRep = 3200;
    const kSpring = 0.08;
    const restLen = Math.min(width, height) * 0.12;
    const damping = 0.22;

    for (let iter = 0; iter < iterations; iter++) {
        const fx = new Map(nodes.map((n) => [n.id, 0]));
        const fy = new Map(nodes.map((n) => [n.id, 0]));

        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const a = nodes[i].id;
                const b = nodes[j].id;
                const pa = pos.get(a);
                const pb = pos.get(b);
                let dx = pa.x - pb.x;
                let dy = pa.y - pb.y;
                let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
                const f = kRep / (dist * dist);
                dx = (dx / dist) * f;
                dy = (dy / dist) * f;
                fx.set(a, fx.get(a) + dx);
                fy.set(a, fy.get(a) + dy);
                fx.set(b, fx.get(b) - dx);
                fy.set(b, fy.get(b) - dy);
            }
        }

        links.forEach((l) => {
            const pa = pos.get(l.source);
            const pb = pos.get(l.target);
            if (!pa || !pb) return;
            let dx = pb.x - pa.x;
            let dy = pb.y - pa.y;
            let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
            const force = kSpring * (dist - restLen);
            dx = (dx / dist) * force;
            dy = (dy / dist) * force;
            fx.set(l.source, fx.get(l.source) + dx);
            fy.set(l.source, fy.get(l.source) + dy);
            fx.set(l.target, fx.get(l.target) - dx);
            fy.set(l.target, fy.get(l.target) - dy);
        });

        nodes.forEach((n) => {
            const p = pos.get(n.id);
            fx.set(n.id, fx.get(n.id) + (cx - p.x) * 0.03);
            fy.set(n.id, fy.get(n.id) + (cy - p.y) * 0.03);
        });

        nodes.forEach((n) => {
            const p = pos.get(n.id);
            p.x += fx.get(n.id) * damping;
            p.y += fy.get(n.id) * damping;
            const pad = 28;
            p.x = Math.max(pad, Math.min(width - pad, p.x));
            p.y = Math.max(pad, Math.min(height - pad, p.y));
        });
    }

    return pos;
}

/**
 * @param {HTMLElement} mount
 * @param {object|null} model — SystemModel 对象
 */
function renderModelForceGraph(mount, model) {
    if (!mount) return;
    const W = 340;
    const H = 260;
    const g = buildGraphFromSystemModel(model || {});

    if (!g.nodes.length) {
        mount.innerHTML = `<svg class="model-force-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" aria-label="关系图空">
            <rect width="100%" height="100%" fill="#f8fafc"/>
            <text x="50%" y="50%" text-anchor="middle" fill="#94a3b8" font-size="12">暂无节点（添加变量与含因变量的关系后显示）</text>
        </svg>`;
        return;
    }

    const pos = runForceLayout(g.nodes, g.links, W, H, 280);
    const nodeR = 14;

    const defs = `<defs>
        <marker id="modelGraphArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#64748b"/>
        </marker>
    </defs>`;

    const edgesSvg = g.links
        .map((l) => {
            const a = pos.get(l.source);
            const b = pos.get(l.target);
            if (!a || !b) return '';
            let x1 = a.x;
            let y1 = a.y;
            let x2 = b.x;
            let y2 = b.y;
            const dx = x2 - x1;
            const dy = y2 - y1;
            const len = Math.sqrt(dx * dx + dy * dy) || 1;
            const shrink = nodeR + 4;
            x1 += (dx / len) * shrink;
            y1 += (dy / len) * shrink;
            x2 -= (dx / len) * shrink;
            y2 -= (dy / len) * shrink;
            return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#modelGraphArrow)"/>`;
        })
        .join('');

    const nodesSvg = g.nodes
        .map((n) => {
            const p = pos.get(n.id);
            if (!p) return '';
            const label = escapeHtmlModel(n.label || n.id.replace(/^var:/, ''));
            return `<g class="model-graph-node">
                <circle cx="${p.x}" cy="${p.y}" r="${nodeR}" fill="#e0e7ff" stroke="#4f46e5" stroke-width="2"/>
                <text x="${p.x}" y="${p.y + 4}" text-anchor="middle" fill="#1e293b" font-size="11" font-weight="500">${label}</text>
            </g>`;
        })
        .join('');

    mount.innerHTML = `<svg class="model-force-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="关系力图">
        <rect width="100%" height="100%" fill="#f8fafc"/>
        ${defs}
        ${edgesSvg}
        ${nodesSvg}
    </svg>`;
}

function escapeHtmlModel(s) {
    if (s == null) return '';
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}

window.buildGraphFromSystemModel = buildGraphFromSystemModel;
window.renderModelForceGraph = renderModelForceGraph;
