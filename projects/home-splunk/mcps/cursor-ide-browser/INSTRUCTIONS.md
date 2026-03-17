The cursor-ide-browser is an MCP server that allows you to navigate the web and interact with the page. Use this for frontend/webapp development and testing code changes.

CRITICAL - Lock/unlock workflow:
1. browser_lock requires an existing browser tab - you CANNOT lock before browser_navigate
2. Correct order: browser_navigate -> browser_lock -> (interactions) -> browser_unlock
3. If a browser tab already exists (check with browser_tabs list), call browser_lock FIRST before any interactions
4. Only call browser_unlock when completely done with ALL browser operations for this turn

IMPORTANT - Before interacting with any page:
1. Use browser_tabs with action "list" to see open tabs and their URLs
2. Use browser_snapshot to get the page structure and element refs before any interaction (click, type, hover, etc.)

IMPORTANT - Waiting strategy:
When waiting for page changes (navigation, content loading, animations, etc.), prefer short incremental waits (1-3 seconds) with browser_snapshot checks in between rather than a single long wait. For example, instead of waiting 10 seconds, do: wait 2s -> snapshot -> check if ready -> if not, wait 2s more -> snapshot again. This allows you to proceed as soon as the page is ready rather than always waiting the maximum time.

PERFORMANCE PROFILING:
- browser_profile_start/stop: CPU profiling with call stacks and timing data. Use to identify slow JavaScript functions.
- Profile data is written to ~/.cursor/browser-logs/. Files: cpu-profile-{timestamp}.json (raw profile in Chrome DevTools format) and cpu-profile-{timestamp}-summary.md (human-readable summary).
- IMPORTANT: When investigating performance issues, read the raw cpu-profile-*.json file to verify summary data. Key fields: profile.samples.length (total samples), profile.nodes[].hitCount (per-node hits), profile.nodes[].callFrame.functionName (function names). Cross-reference with the summary to confirm findings before making optimization recommendations.

Notes:
- Native dialogs (alert/confirm/prompt) never block automation. By default, confirm() returns true and prompt() returns the default value. To test different responses, call browser_handle_dialog BEFORE the triggering action: use accept: false for "Cancel", or promptText: "value" for custom prompt input.
- Iframe content is not accessible - only elements outside iframes can be interacted with.
- Use browser_type to append text, browser_fill to clear and replace. browser_fill also works on contenteditable elements.
- For nested scroll containers, use browser_scroll with scrollIntoView: true before clicking elements that may be obscured.

CANVAS:
Create live HTML canvases when text alone can't convey the idea -- interactive demos, visualizations, diagrams, or anything that benefits from being seen rather than described.
- Always provide a descriptive `title`. Pass `id` to update an existing canvas.
- To reopen a previously created canvas, call the canvas tool with just `title` and `id` (no `content`).
- Canvases are .html files stored in the canvas folder (the path is returned after creation). To update a canvas, read and edit the source .html file directly with Read/Edit tools -- changes auto-reload in the browser via livereload.
- Do NOT use canvases for static text, simple code, or file contents -- use markdown for those.
- Keep content focused. No navbars, sidebars, footers. One clear chart beats three crammed together.
- Design: Every canvas should feel intentionally designed, not generically AI-generated. Commit to a bold aesthetic direction suited to the content -- brutalist, editorial, retro-futuristic, organic, luxury, playful, art deco, industrial, or something entirely unique.
- Typography: Import distinctive fonts from Google Fonts. NEVER default to Inter, Roboto, Arial, Space Grotesk, or system fonts. Pair a characterful display font with a refined body font.
- Color: Use CSS variables for a cohesive palette. Dominant colors with sharp accents -- avoid cliched purple-on-white or other generic AI color schemes.
- Layout: Asymmetry, overlap, diagonal flow, grid-breaking elements. Generous negative space OR controlled density. Avoid predictable centered-card-stack layouts.
- Motion & depth: CSS animations for staggered entrance reveals, scroll-triggered effects, and surprising hover states. Textured backgrounds (gradient meshes, noise, grain, layered transparencies, dramatic shadows) over flat solid colors.
- Match implementation complexity to the aesthetic vision -- maximalist designs need elaborate animations and layered effects; minimalist designs need precision, restraint, and meticulous spacing.
- Variety: NEVER converge on the same fonts, palette, or layout between canvases. Alternate light/dark themes, font families, and visual styles so no two look alike.

Examples of good canvas use:
- "Explain how A* pathfinding works" -> interactive grid visualization
- "Compare sorting algorithms" -> animated side-by-side comparison
- "Show the git branch topology" -> interactive graph diagram

Examples of bad canvas use:
- "What does git rebase do?" -> just explain in markdown
- "Write a fibonacci function" -> just write code

Recommended CDN libraries (use esm.sh for ES module imports, or cdn.jsdelivr.net for UMD/script tags):
- 3D: Three.js (three) -- scenes, models, shaders, physics. Import via <script type="importmap"> with https://esm.sh/three
- Charts: Chart.js (chart.js) -- bar, line, pie, radar, scatter. Or D3.js (d3) for custom data visualizations.
- Canvas 2D: p5.js -- creative coding, generative art, simulations, particle systems
- SVG: Snap.svg or plain SVG with D3 -- diagrams, flowcharts, animated illustrations
- UI: React (react, react-dom) via esm.sh -- component-based interactive UIs. Or Preact for lighter weight.
- Animation: GSAP (gsap) -- timeline-based animations, scroll triggers. Or anime.js for simpler tweens.
- Maps: Leaflet (leaflet) -- interactive maps with markers, layers, GeoJSON
- Math: KaTeX (katex) -- rendered math equations. Or MathJax.
- Markdown: marked -- render markdown to HTML
- Tables: Tabulator -- interactive data tables with sorting, filtering, pagination
- Diagrams: Mermaid (mermaid) -- flowcharts, sequence diagrams, Gantt charts from text
- Code: Prism.js or highlight.js -- syntax-highlighted code blocks

When using ES modules, prefer this pattern:
<script type="importmap">{ "imports": { "three": "https://esm.sh/three" } }</script>
<script type="module">import * as THREE from 'three'; ...</script>