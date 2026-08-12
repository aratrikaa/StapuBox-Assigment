/* Dashboard for the sports content agent. Vanilla JS, no build step. */

const $ = (id) => document.getElementById(id);
const LETTERS = ["A", "B", "C", "D"];

const state = {
  meta: null,
  batch: null,
  selectedTypes: new Set(["mcq", "true_false"]),
};

/* ------------------------------------------------------------------ boot */

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await loadMeta();
  await refreshStats();
});

async function loadMeta() {
  try {
    const meta = await api("/api/meta");
    state.meta = meta;

    $("sport").innerHTML =
      meta.sports.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("") +
      `<option value="__other__">Other…</option>`;

    $("types").innerHTML = meta.types
      .map(
        (t) => `
      <label class="type-card ${state.selectedTypes.has(t.value) ? "selected" : ""}"
             data-type="${t.value}">
        <input type="checkbox" value="${t.value}"
               ${state.selectedTypes.has(t.value) ? "checked" : ""} />
        <span>
          <span class="t-label">${esc(t.label)}</span><br />
          <span class="t-surface">${esc(t.surface)}${
            t.fact_checked ? "" : " · opinion only"
          }</span>
        </span>
      </label>`
      )
      .join("");

    $("types")
      .querySelectorAll("input")
      .forEach((input) => input.addEventListener("change", onTypeToggle));

    // Mirror onTypeToggle's enable/disable rule for the default selection —
    // it only runs on a checkbox change otherwise, so on first load "Mix"
    // would stay enabled even with just one type selected.
    $("mixed").disabled = state.selectedTypes.size === 1;

    const chip = $("status-chip");
    if (meta.api_key_configured) {
      chip.textContent = "agent ready";
      chip.className = "chip chip-ok";
    } else {
      chip.textContent = "ANTHROPIC_API_KEY missing";
      chip.className = "chip chip-bad";
      alert_(
        "error",
        "No API key configured. Copy <code>.env.example</code> to <code>.env</code>, add your <code>ANTHROPIC_API_KEY</code>, and restart the server."
      );
      $("generate").disabled = true;
    }
  } catch (err) {
    alert_("error", `Could not reach the API: ${esc(err.message)}`);
  }
}

function bindEvents() {
  $("generate").addEventListener("click", generate);
  $("regenerate-batch").addEventListener("click", regenerateBatch);
  $("copy-all").addEventListener("click", copyAllCaptions);
  $("clear-history").addEventListener("click", clearHistory);
  $("search-go").addEventListener("click", runSearch);
  $("search-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });
  $("sport").addEventListener("change", onSportChange);
}

function onSportChange() {
  const other = $("sport").value === "__other__";
  $("sport-custom").hidden = !other;
  if (other) $("sport-custom").focus();
}

function selectedSport() {
  const value = $("sport").value;
  return value === "__other__" ? $("sport-custom").value.trim() : value;
}

function onTypeToggle(e) {
  const value = e.target.value;
  if (e.target.checked) state.selectedTypes.add(value);
  else state.selectedTypes.delete(value);

  if (state.selectedTypes.size === 0) {
    e.target.checked = true;
    state.selectedTypes.add(value);
    return;
  }
  e.target.closest(".type-card").classList.toggle("selected", e.target.checked);

  // "Mixed" only means anything with more than one type selected.
  const mixed = $("mixed");
  if (state.selectedTypes.size === 1) mixed.checked = false;
  mixed.disabled = state.selectedTypes.size === 1;
}

/* ------------------------------------------------------------- generation */

async function generate() {
  const sport = selectedSport();
  if (!sport) return alert_("error", "Enter a sport.");

  const btn = $("generate");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-tiny"></span>Generating…';
  clearAlerts();
  try {
    const batch = await api("/api/generate", {
      method: "POST",
      body: {
        sport,
        difficulty: $("difficulty").value,
        types: [...state.selectedTypes],
        count: Number($("count").value),
        mixed: $("mixed").checked && state.selectedTypes.size > 1,
      },
    });
    state.batch = batch;
    renderBatch(batch);
    await refreshStats();
  } catch (err) {
    alert_("error", esc(err.message));
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate batch";
  }
}

async function regenerateBatch() {
  if (!state.batch) return;
  const btn = $("regenerate-batch");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-tiny"></span>Regenerating…';
  clearAlerts();
  try {
    const batch = await api("/api/regenerate-batch", {
      method: "POST",
      body: { batch_id: state.batch.id },
    });
    state.batch = batch;
    renderBatch(batch);
    await refreshStats();
  } catch (err) {
    alert_("error", esc(err.message));
  } finally {
    btn.disabled = false;
    btn.textContent = "Regenerate all";
  }
}

async function regenerateItem(itemId, buttonEl) {
  const card = buttonEl.closest(".card");
  card.classList.add("regenerating");
  buttonEl.disabled = true;
  buttonEl.innerHTML = '<span class="spinner-tiny"></span>Regenerating…';
  try {
    const res = await api("/api/regenerate-item", {
      method: "POST",
      body: { batch_id: state.batch.id, item_id: itemId, refresh_research: true },
    });
    state.batch = res.batch;
    card.replaceWith(renderCard(res.item));
    await refreshStats();
  } catch (err) {
    alert_("error", esc(err.message));
    card.classList.remove("regenerating");
    buttonEl.disabled = false;
    buttonEl.textContent = "Regenerate";
  }
}

/* ------------------------------------------------------------- live search */

async function runSearch() {
  const query = $("search-query").value.trim();
  if (!query) return alert_("error", "Enter a search query.");

  const btn = $("search-go");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-tiny"></span>Searching…';
  try {
    const res = await api("/api/search", { method: "POST", body: { query } });
    $("search-result").hidden = false;
    $("search-answer").textContent = res.answer || "(no live web results for this query)";
    $("search-sources").innerHTML =
      res.sources
        .map(
          (s) =>
            `<li><a href="${esc(s.reference)}" target="_blank" rel="noopener">${esc(
              s.title || s.reference
            )}</a></li>`
        )
        .join("") || "<li>none</li>";
  } catch (err) {
    alert_("error", esc(err.message));
  } finally {
    btn.disabled = false;
    btn.textContent = "Search";
  }
}

/* ---------------------------------------------------------------- render */

function renderBatch(batch) {
  $("results").hidden = false;
  $("regenerate-batch").disabled = false;
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });

  const typeCounts = {};
  batch.items.forEach((i) => (typeCounts[i.type_label] = (typeCounts[i.type_label] || 0) + 1));

  $("results-title").textContent = `${batch.sport} · ${batch.items.length} items`;
  $("results-meta").innerHTML =
    `${esc(batch.difficulty)} · ${Object.entries(typeCounts)
      .map(([k, v]) => `${v}× ${esc(k)}`)
      .join(", ")} · batch <code>${esc(batch.id)}</code>`;

  const cards = $("cards");
  cards.innerHTML = "";
  batch.items.forEach((item) => cards.appendChild(renderCard(item)));

  batch.warnings.forEach((w) => alert_("warn", esc(w)));
  renderEvidence(batch);
}

function renderCard(item) {
  const p = item.payload;
  const card = document.createElement("div");
  card.className = "card";

  const head = `
    <div class="card-head">
      <span class="chip chip-type">${esc(item.type_label)}</span>
      ${item.difficulty ? `<span class="chip chip-muted">${esc(item.difficulty)}</span>` : ""}
      ${groundingChip(item)}
      ${item.attempts > 1 ? `<span class="chip chip-muted">${item.attempts} attempts</span>` : ""}
    </div>`;

  let body = "";
  switch (item.type) {
    case "mcq":
      body = `
        <div class="card-q">${esc(p.question)}</div>
        <div class="options">
          ${p.options
            .map(
              (o, i) => `<div class="option ${
                LETTERS[i] === p.correct_answer ? "correct" : ""
              }"><span class="letter">${LETTERS[i]}</span><span>${esc(o)}</span></div>`
            )
            .join("")}
        </div>
        <div class="explanation">${esc(p.explanation)}</div>`;
      break;

    case "true_false":
      body = `
        <div class="card-q">${esc(p.statement)}</div>
        <div class="options">
          <div class="option ${p.correct_answer ? "correct" : ""}">
            <span class="letter">T</span><span>True</span></div>
          <div class="option ${!p.correct_answer ? "correct" : ""}">
            <span class="letter">F</span><span>False</span></div>
        </div>
        <div class="explanation">${esc(p.explanation)}</div>`;
      break;

    case "poll":
      body = `
        <div class="card-q">${esc(p.prompt)}</div>
        <div class="options">
          ${p.options.map((o) => `<div class="option"><span>${esc(o)}</span></div>`).join("")}
        </div>
        <div class="explanation">No correct answer — opinion-based by design, and
          deliberately not fact-checked.</div>`;
      break;

    case "fill_blank":
      body = `
        <div class="card-q">${esc(p.sentence).replace(
          "___",
          '<span style="color:var(--accent)">______</span>'
        )}</div>
        <div class="options">
          ${p.options
            .map(
              (o, i) => `<div class="option ${
                o === p.correct_answer ? "correct" : ""
              }"><span class="letter">${LETTERS[i]}</span><span>${esc(o)}</span></div>`
            )
            .join("")}
        </div>
        <div class="explanation">${esc(p.explanation)}</div>`;
      break;

    case "guess_number":
      body = `
        <div class="card-q">${esc(p.question)}</div>
        <div class="numeric">
          <div class="stat"><div class="k">Answer</div>
            <div class="v">${num(p.target_number)}${p.unit ? " " + esc(p.unit) : ""}</div></div>
          <div class="stat"><div class="k">Accepted (±${num(p.tolerance)})</div>
            <div class="v">${num(p.acceptable_range[0])} – ${num(p.acceptable_range[1])}</div></div>
        </div>
        <div class="explanation">${esc(p.explanation)}</div>`;
      break;
  }

  const warnings = item.format_warnings.length
    ? `<div class="warnings">⚠ ${item.format_warnings.map(esc).join("<br>⚠ ")}</div>`
    : "";

  const sources = `
    <div class="sources">
      <strong>Sources</strong> · ${esc(item.recommended_surface)}
      ${item.sources
        .map((s) => {
          const badge =
            s.kind === "web_search"
              ? '<span class="chip chip-web">web</span>'
              : s.kind === "vector_db"
              ? '<span class="chip chip-kb">vector DB</span>'
              : '<span class="chip chip-opinion">opinion</span>';
          const label = s.reference && s.reference.startsWith("http")
            ? `<a href="${esc(s.reference)}" target="_blank" rel="noopener">${esc(
                s.title || s.reference
              )}</a>`
            : `<span>${esc(s.title)}${
                s.reference ? ` <code>${esc(s.reference)}</code>` : ""
              }</span>`;
          return `<div class="src">${badge}${label}</div>`;
        })
        .join("")}
    </div>`;

  card.innerHTML =
    head +
    body +
    warnings +
    sources +
    `<div class="card-actions">
       <button class="btn-tiny" data-act="regen">Regenerate</button>
       <button class="btn-tiny" data-act="copy">Copy caption</button>
       <button class="btn-tiny" data-act="sticker">Copy sticker text</button>
     </div>`;

  card.querySelector('[data-act="regen"]').addEventListener("click", (e) =>
    regenerateItem(item.id, e.target)
  );
  card.querySelector('[data-act="copy"]').addEventListener("click", (e) =>
    copy(item.instagram.caption, e.target)
  );
  card.querySelector('[data-act="sticker"]').addEventListener("click", (e) =>
    copy(stickerText(item), e.target)
  );

  return card;
}

function groundingChip(item) {
  if (!item.fact_checked) return '<span class="chip chip-opinion">opinion</span>';
  return item.grounding_kinds
    .map((k) =>
      k === "web_search"
        ? '<span class="chip chip-web">web search</span>'
        : '<span class="chip chip-kb">vector DB</span>'
    )
    .join("");
}

function stickerText(item) {
  const ig = item.instagram;
  const lines = [`[${ig.sticker} sticker]`, ig.question];
  if (ig.options && ig.options.length) {
    ig.options.forEach((o, i) =>
      lines.push(`${i + 1}. ${o}${ig.correct_index === i ? "  ✅" : ""}`)
    );
  }
  if (ig.answer) lines.push(`Answer: ${ig.answer}`, `Accepted: ${ig.accepted}`);
  return lines.join("\n");
}

function renderEvidence(batch) {
  $("evidence").hidden = false;
  $("evidence-count").textContent =
    `${batch.web_sources.length} web · ${batch.kb_sources.length} KB`;
  $("web-brief").textContent = batch.research_summary || "(no live web results for this request)";
  $("web-sources").innerHTML =
    batch.web_sources
      .map(
        (s) =>
          `<li><a href="${esc(s.reference)}" target="_blank" rel="noopener">${esc(
            s.title
          )}</a></li>`
      )
      .join("") || "<li>none</li>";
  $("kb-sources").innerHTML =
    batch.kb_sources
      .map((s) => `<li><code>${esc(s.reference)}</code> — ${esc(s.snippet)}</li>`)
      .join("") || "<li>none</li>";
}

/* ---------------------------------------------------------------- utils */

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
  return data;
}

async function refreshStats() {
  try {
    const h = await api("/api/health");
    $("footer-stats").innerHTML =
      `model <code>${esc(h.model)}</code> · effort ${esc(h.reasoning_effort)} · ` +
      `web search ${h.web_search_enabled ? "on" : "off"} · ` +
      `${h.knowledge_base.documents} KB docs · ${h.history.total} items in history`;
  } catch {
    /* non-fatal */
  }
}

async function clearHistory() {
  if (!confirm("Clear the stored freshness history? Past subjects will become reusable.")) return;
  const res = await api("/api/history", { method: "DELETE" });
  alert_("ok", `Cleared ${res.removed} remembered items.`);
  await refreshStats();
}

async function copyAllCaptions() {
  if (!state.batch) return;
  const text = state.batch.items
    .map((i, n) => `--- ${n + 1}. ${i.type_label} ---\n${i.instagram.caption}`)
    .join("\n\n");
  copy(text, $("copy-all"));
}

async function copy(text, btn) {
  const original = btn.textContent;
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = "Copied ✓";
  } catch {
    btn.textContent = "Copy failed";
  }
  setTimeout(() => (btn.textContent = original), 1400);
}

function alert_(kind, html) {
  const div = document.createElement("div");
  div.className = `alert alert-${kind}`;
  div.innerHTML = html;
  $("alerts").appendChild(div);
}

function clearAlerts() {
  $("alerts").innerHTML = "";
}

function esc(s) {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function num(n) {
  return Number.isInteger(n) ? n : Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
}
