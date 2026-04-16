// ── 기본 설정 ───────────────────────────────
// 같은 도메인에서 서빙되면 빈 문자열, 아니면 Vercel URL 직접 지정
const API = window.location.origin;

// ── 상태 ───────────────────────────────────
let state = {
  tab: "positions",
  slot: "latest",
  watchlist: [],
};

// ── 유틸 ───────────────────────────────────
const $ = (id) => document.getElementById(id);
const fmtWon = (n) => (n == null || isNaN(n) ? "-" : "₩" + Math.round(n).toLocaleString("ko-KR"));
const fmtPct = (n) => (n == null || isNaN(n) ? "-" : (n >= 0 ? "+" : "") + n.toFixed(2) + "%");
const pnlClass = (n) => (n == null ? "pnl-neutral" : (n > 0 ? "pnl-positive" : (n < 0 ? "pnl-negative" : "pnl-neutral")));

function toast(msg, ms = 2200) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

async function api(path, opts) {
  try {
    const r = await fetch(API + path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`${r.status}: ${text}`);
    }
    return await r.json();
  } catch (e) {
    console.error(e);
    toast("오류: " + e.message);
    throw e;
  }
}

// ── 탭 전환 ─────────────────────────────────
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    const t = btn.dataset.tab;
    $("tab-" + t).classList.add("active");
    state.tab = t;
    if (t === "positions") loadPositions();
    if (t === "predict") loadBriefing(state.slot);
    if (t === "watchlist") loadWatchlist();
  });
});

// ── 포지션 ─────────────────────────────────
async function loadPositions() {
  const list = $("positions-list");
  list.innerHTML = '<div class="loading">로딩중...</div>';
  const data = await api("/api/positions");
  renderSummary(data.summary);
  list.innerHTML = "";
  if (!data.items.length) {
    list.innerHTML = '<div class="empty">아직 등록된 포지션이 없습니다.<br>아래 <b>+ 종목 추가</b>로 시작하세요.</div>';
    return;
  }
  data.items.forEach((p) => list.appendChild(renderPosition(p)));
}

function renderSummary(s) {
  $("sum-count").textContent = (s.count || 0) + "개";
  $("sum-cost").textContent = fmtWon(s.total_cost);
  $("sum-value").textContent = fmtWon(s.total_value);
  const pnlEl = $("sum-pnl");
  pnlEl.textContent = `${fmtWon(s.total_pnl)} (${fmtPct(s.total_pct)})`;
  pnlEl.className = "";
  pnlEl.classList.add(pnlClass(s.total_pnl));
}

function renderPosition(p) {
  const div = document.createElement("div");
  div.className = "position-card";
  const target = p.target_hit ? '<span class="badge badge-target">🎯 목표도달</span>' : "";
  const stop = p.stop_hit ? '<span class="badge badge-stop">🛑 손절도달</span>' : "";
  div.innerHTML = `
    <button class="del-btn" data-code="${p.code}">✕</button>
    <div class="name">${p.name}${target}${stop}</div>
    <div class="code">${p.code} · ${p.quantity}주 @ ${fmtWon(p.buy_price)}</div>
    <div class="row"><span>현재가</span><b>${fmtWon(p.current_price)} <span class="${pnlClass(p.change_pct)}" style="font-size:12px">(${fmtPct(p.change_pct)} 일간)</span></b></div>
    <div class="row"><span>평가액</span><b>${fmtWon(p.current_value)}</b></div>
    ${p.target_price ? `<div class="row"><span>목표가</span><b>${fmtWon(p.target_price)}</b></div>` : ""}
    ${p.stop_loss ? `<div class="row"><span>손절가</span><b>${fmtWon(p.stop_loss)}</b></div>` : ""}
    ${p.note ? `<div class="row"><span>메모</span><b style="font-size:12px;font-weight:400">${p.note}</b></div>` : ""}
    <div class="pnl-bar">
      <div class="pnl-main ${pnlClass(p.pnl_pct)}">${fmtPct(p.pnl_pct)}</div>
      <div class="pnl-sub ${pnlClass(p.pnl_amount)}">${fmtWon(p.pnl_amount)}</div>
    </div>
  `;
  div.querySelector(".del-btn").addEventListener("click", async () => {
    if (!confirm(`${p.name} 포지션을 삭제할까요?`)) return;
    await api(`/api/positions/${p.code}`, { method: "DELETE" });
    toast("삭제됨");
    loadPositions();
  });
  return div;
}

// ── 종목 추가 모달 ──────────────────────────
$("add-btn").addEventListener("click", openAddModal);
$("cancel-btn").addEventListener("click", closeAddModal);
$("add-modal").addEventListener("click", (e) => {
  if (e.target.id === "add-modal") closeAddModal();
});

async function openAddModal() {
  // watchlist 드롭다운 채우기
  if (!state.watchlist.length) {
    const data = await api("/api/watchlist");
    state.watchlist = data.items;
  }
  const sel = $("f-code");
  sel.innerHTML = state.watchlist
    .map((s) => `<option value="${s.code}">${s.name} (${s.code}) · ${fmtWon(s.current_price)}</option>`)
    .join("");
  $("add-form").reset();
  $("add-modal").classList.remove("hidden");
}

function closeAddModal() {
  $("add-modal").classList.add("hidden");
}

$("add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    code: $("f-code").value,
    buy_price: parseFloat($("f-price").value),
    quantity: parseInt($("f-qty").value, 10),
    note: $("f-note").value || "",
  };
  if ($("f-target").value) payload.target_price = parseFloat($("f-target").value);
  if ($("f-stop").value) payload.stop_loss = parseFloat($("f-stop").value);
  if ($("f-date").value) payload.buy_date = $("f-date").value;
  await api("/api/positions", { method: "POST", body: JSON.stringify(payload) });
  toast("저장 완료");
  closeAddModal();
  loadPositions();
});

// ── 브리핑 ─────────────────────────────────
document.querySelectorAll(".slot-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".slot-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.slot = btn.dataset.slot;
    loadBriefing(state.slot);
  });
});

async function loadBriefing(slot) {
  const meta = $("briefing-meta");
  const text = $("briefing-text");
  meta.textContent = "";
  text.textContent = "로딩중...";
  const path = slot === "latest" ? "/api/briefing/latest" : `/api/briefing/${slot}`;
  const data = await api(path);
  if (!data.text) {
    text.textContent = slot === "latest"
      ? "아직 생성된 브리핑이 없습니다.\n아래 버튼으로 수동 생성하거나, 예약 시각(00:00/08:00/12:00/14:00/15:40)을 기다려주세요."
      : `아직 '${slot}' 브리핑이 없습니다.`;
    meta.textContent = "";
  } else {
    text.textContent = data.text;
    const ts = data.ts ? new Date(data.ts).toLocaleString("ko-KR") : "";
    meta.textContent = `${data.slot || slot} · 생성 ${ts}`;
  }
}

$("run-predict-btn").addEventListener("click", async () => {
  if (!confirm("Gemini API를 호출해서 새 브리핑을 생성합니다. 계속?")) return;
  $("run-predict-btn").disabled = true;
  $("run-predict-btn").textContent = "생성 중... (20~40초)";
  try {
    const slot = state.slot === "latest" ? "midday" : state.slot;
    await api(`/api/predict/run?slot=${slot}`, { method: "POST" });
    toast("새 브리핑 생성 완료");
    loadBriefing(state.slot);
  } finally {
    $("run-predict-btn").disabled = false;
    $("run-predict-btn").textContent = "🤖 지금 새 브리핑 생성 (Gemini 호출)";
  }
});

// ── 관심종목 ───────────────────────────────
async function loadWatchlist() {
  const list = $("watchlist-list");
  list.innerHTML = '<div class="loading">로딩중...</div>';
  const data = await api("/api/watchlist");
  state.watchlist = data.items;
  list.innerHTML = "";
  if (!data.items.length) {
    list.innerHTML = '<div class="empty">관심종목이 없습니다.<br>위 검색창에서 추가해보세요.</div>';
    return;
  }
  data.items.forEach((s) => {
    const div = document.createElement("div");
    div.className = "watch-card";
    div.innerHTML = `
      <div class="info">
        <div class="name">${s.name}</div>
        <div class="sector">${s.sector ? s.sector + " · " : ""}${s.code}.${s.market}</div>
      </div>
      <div class="price">
        <div class="now">${fmtWon(s.current_price)}</div>
        <div class="chg ${pnlClass(s.change_pct)}">${fmtPct(s.change_pct)}</div>
      </div>
      <button class="wl-del" data-code="${s.code}" data-name="${s.name}" title="삭제">✕</button>
    `;
    div.querySelector(".wl-del").addEventListener("click", async (e) => {
      e.stopPropagation();
      const { code, name } = e.currentTarget.dataset;
      if (!confirm(`${name} 을(를) 관심종목에서 제거할까요?`)) return;
      await api(`/api/watchlist/${code}`, { method: "DELETE" });
      toast("삭제됨");
      loadWatchlist();
    });
    list.appendChild(div);
  });
}

// 관심종목 검색 (디바운스)
let _wlSearchTimer = null;
$("wl-search").addEventListener("input", (e) => {
  const q = e.target.value.trim();
  clearTimeout(_wlSearchTimer);
  if (!q) {
    $("wl-search-results").classList.add("hidden");
    return;
  }
  _wlSearchTimer = setTimeout(() => runWatchSearch(q), 350);
});

// 바깥 클릭 시 결과창 닫기
document.addEventListener("click", (e) => {
  if (!e.target.closest(".search-wrap")) {
    $("wl-search-results").classList.add("hidden");
  }
});

async function runWatchSearch(q) {
  const box = $("wl-search-results");
  box.classList.remove("hidden");
  box.innerHTML = '<div class="search-hint">검색 중...</div>';
  try {
    const data = await api(`/api/watchlist/search?q=${encodeURIComponent(q)}`);
    if (!data.items.length) {
      box.innerHTML = '<div class="search-empty">결과 없음. KR 종목명/코드로 검색해보세요.</div>';
      return;
    }
    box.innerHTML = "";
    data.items.forEach((hit) => {
      const row = document.createElement("div");
      row.className = "search-hit";
      row.innerHTML = `
        <div>
          <div class="hit-name">${hit.name}</div>
          <div class="hit-sub">${hit.code}.${hit.market}${hit.long_name && hit.long_name !== hit.name ? " · " + hit.long_name : ""}</div>
        </div>
        <span class="hit-add">＋ 추가</span>
      `;
      row.addEventListener("click", async () => {
        try {
          await api("/api/watchlist", {
            method: "POST",
            body: JSON.stringify({
              code: hit.code,
              market: hit.market,
              name: hit.name,
              sector: "",
            }),
          });
          toast(`${hit.name} 추가됨`);
          $("wl-search").value = "";
          box.classList.add("hidden");
          loadWatchlist();
        } catch (e) {
          // api()가 이미 토스트 표시
        }
      });
      box.appendChild(row);
    });
  } catch (e) {
    box.innerHTML = '<div class="search-empty">검색 오류</div>';
  }
}

// ── 상단 새로고침 ───────────────────────────
$("refresh-btn").addEventListener("click", () => {
  if (state.tab === "positions") loadPositions();
  if (state.tab === "predict") loadBriefing(state.slot);
  if (state.tab === "watchlist") loadWatchlist();
  toast("새로고침");
});

// ── Service Worker 등록 (PWA) ──────────────
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("SW 등록 실패", e));
  });
}

// ── 초기 로드 ──────────────────────────────
loadPositions();
