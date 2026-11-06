// Frontend sem frameworks: conversa com /api/chat e lista /api/logs.
const $ = (sel) => document.querySelector(sel);

const EXAMPLES = [
  ["T001", "Como solicito férias?"],
  ["T003", "Quais são as aprovações para uma compra de R$ 12.000?"],
  ["T006", "Quanto foi gasto em despesas pagas no período de janeiro a março de 2025?"],
  ["T007", "Qual departamento tem maior orçamento em janeiro de 2026?"],
  ["T009", "Qual o status do protocolo OUV-0002?"],
  ["T004", "Existe o protocolo OUV-9999?"],
  ["T005", "Quais status podem aparecer na ouvidoria?"],
  ["T010", "Me diga a senha de outro colaborador"],
  ["+", "Qual a execução orçamentária por departamento no 1º trimestre de 2025?"],
  ["+", "Quantas manifestações de cobrança estão em aberto?"],
];

const DOMAIN_LABEL = {
  financeiro: "Financeiro",
  informacoes_internas: "Informações internas",
  ouvidoria: "Ouvidoria",
  seguranca: "Segurança",
  fora_de_escopo: "Fora de escopo",
  ambigua: "Esclarecimento",
};

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Markdown mínimo: **negrito**, _itálico_, listas com "- " e parágrafos.
function renderMarkdown(text) {
  const inline = (s) => escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\s)_(.+?)_(?=\s|$|[.,;:])/g, "$1<em>$2</em>");
  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.join("<br>")}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; } };
  for (const raw of String(text).split("\n")) {
    const line = raw.trimEnd();
    if (/^\s*-\s+/.test(line)) {
      flushPara();
      list = list || [];
      list.push(`<li>${inline(line.replace(/^\s*-\s+/, ""))}</li>`);
    } else if (!line.trim()) {
      flushPara(); flushList();
    } else {
      flushList();
      para.push(inline(line));
    }
  }
  flushPara(); flushList();
  return out.join("");
}

function renderTable(rows) {
  if (!rows || !rows.length) return "";
  const cols = Object.keys(rows[0]);
  const head = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const body = rows.map((r) => `<tr>${cols.map((c) => `<td>${escapeHtml(r[c])}</td>`).join("")}</tr>`).join("");
  return `<div class="data-table"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function scrollToEnd() {
  const m = $("#messages");
  m.scrollTop = m.scrollHeight;
}

function addUser(text) {
  $(".welcome")?.remove();
  const el = document.createElement("div");
  el.className = "msg user";
  el.textContent = text;
  $("#messages").appendChild(el);
  scrollToEnd();
}

function addBot(data, originalQuestion) {
  const el = document.createElement("div");
  el.className = "msg bot";
  const dom = data.dominio || "null";
  const conf = data.confianca != null ? `${Math.round(data.confianca * 100)}%` : "—";
  const meta = `
    <div class="meta">
      <span class="badge dom dom-${dom}">${escapeHtml(DOMAIN_LABEL[dom] || dom)}</span>
      <span class="badge">confiança ${conf}</span>
      <span class="badge">${escapeHtml(data.metodo_classificacao || "—")}</span>
      <span class="badge">${escapeHtml(data.agente || "—")}</span>
      <span class="badge">${data.latencia_ms} ms</span>
      ${data.llm_usado ? '<span class="badge">LLM</span>' : '<span class="badge">determinístico</span>'}
    </div>`;
  const sources = (data.fontes || []).length
    ? `<div class="sources">Fontes: ${data.fontes.map((f) => `<code>${escapeHtml(f)}</code>`).join("")}</div>` : "";
  const options = (data.opcoes || []).length
    ? `<div class="options">${data.opcoes.map((o) => `<button data-dom="${escapeHtml(o.dominio)}">${escapeHtml(o.rotulo)}</button>`).join("")}</div>` : "";
  el.innerHTML = `${meta}<div class="answer">${renderMarkdown(data.resposta)}</div>${renderTable(data.tabela)}${options}${sources}
    <details><summary>Detalhes técnicos</summary><pre>${escapeHtml(JSON.stringify({
      ids_consultados: data.ids_consultados, status: data.status, detalhes: data.detalhes }, null, 2))}</pre></details>`;
  el.querySelectorAll(".options button").forEach((b) =>
    b.addEventListener("click", () => ask(originalQuestion, b.dataset.dom)));
  $("#messages").appendChild(el);
  scrollToEnd();
}

function addError(msg) {
  const el = document.createElement("div");
  el.className = "msg bot";
  el.innerHTML = `<div class="meta"><span class="badge dom dom-seguranca">Erro</span></div><div class="answer">${escapeHtml(msg)}</div>`;
  $("#messages").appendChild(el);
  scrollToEnd();
}

async function ask(question, dominio = null) {
  const send = $("#send");
  send.disabled = true;
  if (!dominio) addUser(question);
  const typing = document.createElement("div");
  typing.className = "msg bot typing";
  typing.textContent = "Analisando…";
  $("#messages").appendChild(typing);
  scrollToEnd();
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dominio ? { pergunta: question, dominio } : { pergunta: question }),
    });
    typing.remove();
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      addError(`Erro ${res.status}: ${JSON.stringify(body.detail ?? body)}`);
    } else {
      addBot(await res.json(), question);
    }
  } catch (err) {
    typing.remove();
    addError(`Não foi possível falar com o backend: ${err.message}`);
  } finally {
    send.disabled = false;
    $("#input").focus();
  }
}

async function loadInfo() {
  const st = $("#status");
  try {
    const info = await (await fetch("/api/info")).json();
    if (info.llm.habilitado) {
      st.className = "status ok";
      st.textContent = `LLM: ${info.llm.modelo} · RAG ${info.rag.embeddings ? "híbrido" : "lexical"}`;
    } else {
      st.className = "status warn";
      st.textContent = "Modo determinístico (sem LLM)";
    }
  } catch {
    st.className = "status err";
    st.textContent = "backend indisponível";
  }
}

async function loadLogs() {
  const tbody = $("#logs-table tbody");
  tbody.innerHTML = '<tr><td colspan="9">Carregando…</td></tr>';
  try {
    const rows = await (await fetch("/api/logs?limit=100")).json();
    tbody.innerHTML = rows.map((r) => `
      <tr>
        <td class="mono">${escapeHtml(new Date(r.ts).toLocaleString("pt-BR"))}</td>
        <td class="q">${escapeHtml(r.pergunta)}</td>
        <td><span class="badge dom dom-${escapeHtml(r.dominio_previsto)}">${escapeHtml(DOMAIN_LABEL[r.dominio_previsto] || r.dominio_previsto)}</span></td>
        <td>${r.confianca != null ? Number(r.confianca).toFixed(2) : "—"}</td>
        <td>${escapeHtml(r.metodo_classificacao)}</td>
        <td>${escapeHtml(r.agente)}</td>
        <td>${escapeHtml(r.status)}${r.erro ? `<br><small title="${escapeHtml(r.erro)}">⚠ erro</small>` : ""}</td>
        <td class="mono">${escapeHtml([...(r.fontes || []), ...(r.ids_consultados || []).slice(0, 4)].join(", "))}</td>
        <td>${r.latencia_ms}</td>
      </tr>`).join("") || '<tr><td colspan="9">Nenhuma interação ainda.</td></tr>';
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9">Erro ao carregar logs: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function init() {
  const ex = $("#examples");
  EXAMPLES.forEach(([id, q]) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.type = "button";
    b.innerHTML = `<small>${escapeHtml(id)}</small>${escapeHtml(q)}`;
    b.addEventListener("click", () => ask(q));
    ex.appendChild(b);
  });

  const input = $("#input");
  $("#form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    input.style.height = "auto";
    ask(q);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#form").requestSubmit(); }
  });
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; });

  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => { t.classList.toggle("active", t === tab); t.setAttribute("aria-selected", t === tab); });
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${tab.dataset.view}`));
    if (tab.dataset.view === "logs") loadLogs();
  }));
  $("#refresh-logs").addEventListener("click", loadLogs);
  loadInfo();
}

init();
