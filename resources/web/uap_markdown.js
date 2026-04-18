/**
 * UAP Markdown：marked + highlight.js + DOMPurify + Mermaid（按需 run）
 * 依赖：全局 marked、DOMPurify、hljs、mermaid（由 index.html 先于本文件加载）
 */
(function () {
    'use strict';

    var MAX_MARKDOWN_CHARS = 200000;

    function escapeHtmlFallback(s) {
        if (s == null) return '';
        var t = String(s);
        return t
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function plainTextToSafeHtml(s) {
        return '<p>' + escapeHtmlFallback(s).replace(/\n/g, '<br>') + '</p>';
    }

    var mermaidInited = false;

    function ensureMermaid() {
        if (mermaidInited || typeof mermaid === 'undefined') return;
        try {
            mermaid.initialize({
                startOnLoad: false,
                securityLevel: 'strict',
                theme: 'dark',
            });
            mermaidInited = true;
        } catch (e) {
            console.warn('[UAPMarkdown] mermaid.initialize failed', e);
        }
    }

    function purifyHtml(html) {
        if (typeof DOMPurify === 'undefined') return escapeHtmlFallback(html);
        return DOMPurify.sanitize(html, {
            USE_PROFILES: { html: true },
            ADD_TAGS: [
                'input',
                'svg',
                'path',
                'g',
                'defs',
                'marker',
                'line',
                'rect',
                'circle',
                'ellipse',
                'polygon',
                'polyline',
                'text',
                'tspan',
                'foreignObject',
                'use',
                'clipPath',
                'mask',
                'pattern',
                'linearGradient',
                'radialGradient',
                'stop',
            ],
            ADD_ATTR: [
                'checked',
                'disabled',
                'type',
                'viewBox',
                'preserveAspectRatio',
                'xmlns',
                'fill',
                'stroke',
                'stroke-width',
                'd',
                'x',
                'y',
                'x1',
                'y1',
                'x2',
                'y2',
                'cx',
                'cy',
                'r',
                'rx',
                'ry',
                'width',
                'height',
                'points',
                'transform',
                'class',
                'id',
                'marker-end',
                'marker-start',
                'marker-mid',
                'text-anchor',
                'dominant-baseline',
                'style',
            ],
        });
    }

    function highlightCodeBlock(code, lang) {
        if (typeof hljs === 'undefined') {
            return '<pre><code>' + escapeHtmlFallback(code) + '</code></pre>';
        }
        var trimmed = (lang || '').trim().toLowerCase();
        try {
            if (trimmed && hljs.getLanguage(trimmed)) {
                var r = hljs.highlight(code, { language: trimmed, ignoreIllegals: true });
                return (
                    '<pre><code class="hljs language-' +
                    escapeHtmlFallback(trimmed) +
                    '">' +
                    r.value +
                    '</code></pre>'
                );
            }
            var auto = hljs.highlightAuto(code);
            return '<pre><code class="hljs">' + auto.value + '</code></pre>';
        } catch (e) {
            return '<pre><code class="hljs">' + escapeHtmlFallback(code) + '</code></pre>';
        }
    }

    var markedRendererInstalled = false;

    function installMarkedRenderer() {
        if (markedRendererInstalled || typeof marked === 'undefined' || !marked.use) return;
        marked.use({
            gfm: true,
            breaks: true,
            renderer: {
                code: function (token) {
                    var text = token.text || '';
                    var lang = (token.lang || '').trim().toLowerCase();
                    if (lang === 'mermaid') {
                        return (
                            '<div class="uap-mermaid"><pre class="mermaid">' +
                            escapeHtmlFallback(text) +
                            '</pre></div>\n'
                        );
                    }
                    return highlightCodeBlock(text, token.lang || '');
                },
            },
        });
        markedRendererInstalled = true;
    }

    function renderMarkdownToSafeHtml(markdown) {
        var md = markdown == null ? '' : String(markdown);
        if (md.length > MAX_MARKDOWN_CHARS) {
            md =
                md.slice(0, MAX_MARKDOWN_CHARS - 80) +
                '\n\n…（内容过长，已截断；完整内容请查看原始回复。）';
        }
        if (typeof marked === 'undefined' || !marked.parse) {
            return plainTextToSafeHtml(md);
        }
        installMarkedRenderer();
        var raw;
        try {
            raw = marked.parse(md);
        } catch (e) {
            console.warn('[UAPMarkdown] marked.parse failed', e);
            return plainTextToSafeHtml(md);
        }
        return purifyHtml(raw);
    }

    function finalizeRichContent(root) {
        if (!root) return Promise.resolve();
        ensureMermaid();
        if (typeof mermaid === 'undefined' || !mermaid.run) {
            return Promise.resolve();
        }
        var nodes = root.querySelectorAll('pre.mermaid');
        if (!nodes.length) return Promise.resolve();
        var list = [];
        for (var i = 0; i < nodes.length; i++) {
            list.push(nodes[i]);
        }
        return mermaid.run({ nodes: list }).catch(function (e) {
            console.warn('[UAPMarkdown] mermaid.run failed', e);
        });
    }

    window.UAPMarkdown = {
        renderMarkdownToSafeHtml: renderMarkdownToSafeHtml,
        finalizeRichContent: finalizeRichContent,
        MAX_MARKDOWN_CHARS: MAX_MARKDOWN_CHARS,
    };
})();
