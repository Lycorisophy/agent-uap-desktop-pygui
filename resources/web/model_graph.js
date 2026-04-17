/**
 * 系统模型关系图：与 entity_graph.build_entity_graph_payload 一致的边规则，
 * 力导向布局（无外部依赖）+ SVG 渲染；支持平移/缩放画布与拖拽节点。
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

function svgClientToSvgUser(svg, clientX, clientY) {
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
}

function clamp(n, lo, hi) {
    return Math.max(lo, Math.min(hi, n));
}

function edgeEndpoints(pos, link, nodeR) {
    const a = pos.get(link.source);
    const b = pos.get(link.target);
    if (!a || !b) return null;
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
    return { x1, y1, x2, y2 };
}

function applyGraphGeometry(state) {
    const { pos, links, lineEls, nodeEls, nodeR, W, H } = state;
    links.forEach((l, i) => {
        const ep = edgeEndpoints(pos, l, nodeR);
        const line = lineEls[i];
        if (!line || !ep) return;
        line.setAttribute('x1', String(ep.x1));
        line.setAttribute('y1', String(ep.y1));
        line.setAttribute('x2', String(ep.x2));
        line.setAttribute('y2', String(ep.y2));
    });
    nodeEls.forEach((g, id) => {
        const p = pos.get(id);
        if (!p) return;
        g.setAttribute('transform', `translate(${p.x},${p.y})`);
    });
}

function applyViewportTransform(svg) {
    const st = svg._modelGraphState;
    if (!st) return;
    const vp = svg.querySelector('.mg-viewport');
    const zg = svg.querySelector('.mg-zoom');
    if (vp) vp.setAttribute('transform', `translate(${st.tx},${st.ty})`);
    if (zg) zg.setAttribute('transform', `scale(${st.s})`);
}

function attachModelGraphInteractions(mount, svg, graph, pos, W, H, nodeR) {
    if (mount._modelGraphCleanup) {
        mount._modelGraphCleanup();
        mount._modelGraphCleanup = null;
    }

    const lineEls = Array.from(svg.querySelectorAll('line.mg-edge'));
    const nodeEls = new Map();
    svg.querySelectorAll('g.model-graph-node[data-node-id]').forEach((g) => {
        nodeEls.set(g.getAttribute('data-node-id'), g);
    });

    const st = {
        pos,
        links: graph.links,
        lineEls,
        nodeEls,
        nodeR,
        W,
        H,
        tx: 0,
        ty: 0,
        s: 1,
    };
    svg._modelGraphState = st;

    const pad = 28;
    const clampPos = (p) => {
        p.x = clamp(p.x, pad, W - pad);
        p.y = clamp(p.y, pad, H - pad);
    };

    let drag = null;

    const onWheel = (e) => {
        e.preventDefault();
        const { x: mx, y: my } = svgClientToSvgUser(svg, e.clientX, e.clientY);
        const gx = (mx - st.tx) / st.s;
        const gy = (my - st.ty) / st.s;
        const factor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
        const ns = clamp(st.s * factor, 0.25, 4);
        st.tx = mx - gx * ns;
        st.ty = my - gy * ns;
        st.s = ns;
        applyViewportTransform(svg);
    };

    const onPointerDownBg = (e) => {
        if (e.button !== 0 && e.button !== 1) return;
        e.preventDefault();
        const p0 = svgClientToSvgUser(svg, e.clientX, e.clientY);
        drag = { kind: 'pan', start: p0, tx0: st.tx, ty0: st.ty };
        if (bg) bg.setPointerCapture(e.pointerId);
    };

    const onPointerDownNode = (e) => {
        e.stopPropagation();
        if (e.button !== 0) return;
        const id = e.currentTarget.getAttribute('data-node-id');
        if (!id) return;
        e.preventDefault();
        drag = { kind: 'node', id };
        e.currentTarget.classList.add('mg-dragging');
        e.currentTarget.setPointerCapture(e.pointerId);
    };

    const onPointerMove = (e) => {
        if (!drag) return;
        const p = svgClientToSvgUser(svg, e.clientX, e.clientY);
        if (drag.kind === 'pan') {
            st.tx = drag.tx0 + (p.x - drag.start.x);
            st.ty = drag.ty0 + (p.y - drag.start.y);
            applyViewportTransform(svg);
        } else if (drag.kind === 'node') {
            const gx = (p.x - st.tx) / st.s;
            const gy = (p.y - st.ty) / st.s;
            const np = st.pos.get(drag.id);
            if (np) {
                np.x = gx;
                np.y = gy;
                clampPos(np);
                applyGraphGeometry(st);
            }
        }
    };

    const endDrag = () => {
        if (!drag) return;
        if (drag.kind === 'node') {
            const g = st.nodeEls.get(drag.id);
            if (g) g.classList.remove('mg-dragging');
        }
        drag = null;
    };

    const bg = svg.querySelector('.mg-bg-pan');
    if (bg) {
        bg.addEventListener('pointerdown', onPointerDownBg);
    }
    nodeEls.forEach((g) => {
        g.addEventListener('pointerdown', onPointerDownNode);
    });
    svg.addEventListener('pointermove', onPointerMove, true);
    svg.addEventListener('pointerup', endDrag);
    svg.addEventListener('pointercancel', endDrag);
    svg.addEventListener('lostpointercapture', endDrag);
    svg.addEventListener('wheel', onWheel, { passive: false });

    mount._modelGraphCleanup = () => {
        if (bg) bg.removeEventListener('pointerdown', onPointerDownBg);
        nodeEls.forEach((g) => {
            g.removeEventListener('pointerdown', onPointerDownNode);
        });
        svg.removeEventListener('pointermove', onPointerMove, true);
        svg.removeEventListener('pointerup', endDrag);
        svg.removeEventListener('pointercancel', endDrag);
        svg.removeEventListener('lostpointercapture', endDrag);
        svg.removeEventListener('wheel', onWheel);
        delete svg._modelGraphState;
    };
}

/**
 * @param {HTMLElement} mount
 * @param {object|null} model — SystemModel 对象
 */
function renderModelForceGraph(mount, model) {
    if (!mount) return;
    if (mount._modelGraphCleanup) {
        mount._modelGraphCleanup();
        mount._modelGraphCleanup = null;
    }

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
            const ep = edgeEndpoints(pos, l, nodeR);
            if (!ep) return '';
            return `<line class="mg-edge" pointer-events="none" x1="${ep.x1}" y1="${ep.y1}" x2="${ep.x2}" y2="${ep.y2}" stroke="#94a3b8" stroke-width="1.5" marker-end="url(#modelGraphArrow)"/>`;
        })
        .join('');

    const nodesSvg = g.nodes
        .map((n) => {
            const p = pos.get(n.id);
            if (!p) return '';
            const label = escapeHtmlModel(n.label || n.id.replace(/^var:/, ''));
            return `<g class="model-graph-node" data-node-id="${escapeAttrModel(n.id)}" transform="translate(${p.x},${p.y})">
                <circle cx="0" cy="0" r="${nodeR}" fill="#e0e7ff" stroke="#4f46e5" stroke-width="2"/>
                <text x="0" y="4" text-anchor="middle" fill="#1e293b" font-size="11" font-weight="500">${label}</text>
            </g>`;
        })
        .join('');

    mount.innerHTML = `<svg class="model-force-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="关系力图">
        ${defs}
        <g class="mg-viewport" transform="translate(0,0)">
            <g class="mg-zoom" transform="scale(1)">
                <rect class="mg-bg-pan" x="0" y="0" width="${W}" height="${H}" fill="#f8fafc"/>
                ${edgesSvg}
                ${nodesSvg}
            </g>
        </g>
    </svg>`;

    const svg = mount.querySelector('svg.model-force-svg');
    if (svg) {
        attachModelGraphInteractions(mount, svg, g, pos, W, H, nodeR);
    }
}

function escapeHtmlModel(s) {
    if (s == null) return '';
    const div = document.createElement('div');
    div.textContent = String(s);
    return div.innerHTML;
}

function escapeAttrModel(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;');
}

window.buildGraphFromSystemModel = buildGraphFromSystemModel;
window.renderModelForceGraph = renderModelForceGraph;
