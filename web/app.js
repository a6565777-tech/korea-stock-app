// ── 기본 설정 ───────────────────────────────
// 같은 도메인에서 서빙되면 빈 문자열, 아니면 Vercel URL 직접 지정
const API = window.location.origin;

// ── 상태 ───────────────────────────────────
let state = {
  tab: "positions",
  slot: "realtime",
  watchlist: [],
};

// ── 유틸 ───────────────────────────────────
const $ = (id) => document.getElementById(id);
const fmtWon = (n) => (n == null || isNaN(n) ? "-" : "₩" + Math.round(n).toLocaleString("ko-KR"));
const fmtPct = (n) => (n == null || isNaN(n) ? "-" : (n >= 0 ? "+" : "") + n.toFixed(2) + "%");
const pnlClass = (n) => (n == null ? "pnl-neutral" : (n > 0 ? "pnl-positive" : (n < 0 ? "pnl-negative" : "pnl-neutral")));

// ── localStorage 캐시 (앱 재실행 시 즉시 표시용) ──
const CACHE_PREFIX = "stockapp_v1_";
function cacheGet(key) {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + key);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}
function cacheSet(key, data) {
  try {
    localStorage.setItem(CACHE_PREFIX + key, JSON.stringify({ data, savedAt: Date.now() }));
  } catch {}
}
function cacheAge(cached) {
  if (!cached || !cached.savedAt) return null;
  const mins = Math.round((Date.now() - cached.savedAt) / 60000);
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}시간 전`;
  return `${Math.round(hrs / 24)}일 전`;
}

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
      // 서버가 JSON으로 에러를 주면 구조화된 정보 그대로 throw
      let body = null;
      try { body = await r.json(); } catch { body = await r.text(); }
      const err = new Error(
        typeof body === "object" && body.user_message
          ? body.user_message
          : `HTTP ${r.status}`
      );
      err.status = r.status;
      err.body = body;
      throw err;
    }
    return await r.json();
  } catch (e) {
    console.error(e);
    // toast는 짧은 요약만, 상세는 호출자가 처리
    toast((e.status ? `[${e.status}] ` : "") + (e.message || "오류").slice(0, 80), 3500);
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
function renderPositionsData(data, fromCache = false) {
  const list = $("positions-list");
  renderSummary(data.summary || { count: 0, total_cost: 0, total_value: 0, total_pnl: 0, total_pct: 0 });
  list.innerHTML = "";
  if (!data.items || !data.items.length) {
    list.innerHTML = '<div class="empty">아직 등록된 포지션이 없습니다.<br>아래 <b>+ 종목 추가</b>로 시작하세요.</div>';
    return;
  }
  data.items.forEach((p) => list.appendChild(renderPosition(p)));
}

async function loadPositions() {
  const list = $("positions-list");
  // 1. 캐시 즉시 표시 (있으면)
  const cached = cacheGet("positions");
  if (cached && cached.data) {
    renderPositionsData(cached.data, true);
  } else {
    list.innerHTML = '<div class="loading">로딩중...</div>';
  }
  // 2. 백그라운드로 신선한 데이터 받아서 갱신
  try {
    const data = await api("/api/positions");
    cacheSet("positions", data);
    renderPositionsData(data, false);
  } catch (e) {
    // 네트워크 실패 시: 캐시라도 남아있으면 그대로 두고, 없으면 에러 표시
    if (!cached) {
      list.innerHTML = '<div class="empty">서버 연결 실패. 잠시 후 새로고침(↻).</div>';
    }
  }
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

// 슬롯별 메타: 예약 시각, 자동 스케줄 여부
const SLOT_INFO = {
  realtime:  { icon: "⚡", label: "실시간",    scheduled: null,      autoGen: true  },
  overnight: { icon: "🌙", label: "자정",      scheduled: "00:00",   autoGen: false },
  morning:   { icon: "🌅", label: "아침",      scheduled: "08:00",   autoGen: false },
  midday:    { icon: "🍱", label: "점심",      scheduled: "12:00",   autoGen: false },
  afternoon: { icon: "⏰", label: "오후",      scheduled: "14:00",   autoGen: false },
  closing:   { icon: "🔔", label: "마감",      scheduled: "15:40",   autoGen: false },
};

function updateBriefingControls(slot) {
  // 실시간 탭에서만 수동 생성 버튼 노출. 예약 슬롯은 조회 전용.
  const btn = $("run-predict-btn");
  if (!btn) return;
  if (slot === "realtime") {
    btn.style.display = "";
    btn.textContent = "🤖 지금 새 브리핑 생성 (Gemini 호출)";
  } else {
    btn.style.display = "none";
  }
}

document.querySelectorAll(".slot-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".slot-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.slot = btn.dataset.slot;
    updateBriefingControls(state.slot);
    loadBriefing(state.slot);
  });
});

// 초기 로드 시에도 현재 활성 슬롯 기준으로 버튼 표시 제어
updateBriefingControls(state.slot);

function _ageMinutes(isoTs) {
  if (!isoTs) return null;
  const t = new Date(isoTs).getTime();
  if (isNaN(t)) return null;
  return Math.round((Date.now() - t) / 60000);
}

function _ageLabel(mins) {
  if (mins == null) return "";
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}시간 전`;
  return `${Math.floor(hrs / 24)}일 전`;
}

function renderBriefingData(data, slot, fromCache = false) {
  const meta = $("briefing-meta");
  const text = $("briefing-text");
  const banner = $("briefing-banner");
  banner.classList.add("hidden");
  banner.textContent = "";

  if (!data || !data.text) {
    if (slot === "realtime") {
      text.textContent =
        "아직 생성된 실시간 브리핑이 없습니다.\n" +
        "아래 버튼으로 지금(현재 시각 기준) 생성하세요.";
    } else {
      const info = SLOT_INFO[slot];
      const sched = info ? info.scheduled : "";
      text.textContent =
        `아직 '${info ? info.label : slot}' 슬롯 브리핑이 없습니다.\n\n` +
        (sched ? `이 브리핑은 매 영업일 ${sched} 자동 생성됩니다.\n` : "") +
        `즉시 현재 시각 기준 분석을 보려면 [⚡ 실시간] 탭으로 이동하세요.`;
    }
    meta.textContent = "";
  } else {
    text.textContent = data.text;
    const ageMin = _ageMinutes(data.ts);
    const ageStr = _ageLabel(ageMin);
    const tsAbs = data.ts ? new Date(data.ts).toLocaleString("ko-KR") : "";
    meta.textContent = `${data.slot || slot} · ${ageStr ? ageStr + " · " : ""}${tsAbs}${fromCache ? " (캐시)" : ""}`;

    // 실시간 탭은 오래된 값이면 경고 배너
    if (slot === "realtime" && ageMin != null && ageMin >= 30) {
      banner.classList.remove("hidden");
      banner.innerHTML =
        `⚠️ 실시간 브리핑이 <b>${ageStr}</b> 생성된 내용입니다. ` +
        `시세·뉴스가 바뀌었을 수 있어요. 아래 <b>🤖 지금 새 브리핑 생성</b>으로 최신화하세요.`;
    }
  }
}

async function loadBriefing(slot) {
  const text = $("briefing-text");
  const meta = $("briefing-meta");
  const cacheKey = `briefing_${slot}`;
  // 1. 캐시 즉시 표시
  const cached = cacheGet(cacheKey);
  if (cached && cached.data) {
    renderBriefingData(cached.data, slot, true);
  } else {
    text.textContent = "로딩중...";
    meta.textContent = "";
  }
  // 2. 백그라운드로 최신 데이터
  try {
    const data = await api(`/api/briefing/${slot}`);
    cacheSet(cacheKey, data);
    renderBriefingData(data, slot, false);
  } catch (e) {
    if (!cached) {
      text.textContent = "서버 연결 실패. 잠시 후 새로고침(↻).";
    }
    // 캐시 있으면 그대로 두기 (사용자가 기존 브리핑 계속 볼 수 있게)
  }
}

$("run-predict-btn").addEventListener("click", async () => {
  if (!confirm("Gemini API를 호출해서 새 브리핑을 생성합니다. 계속?")) return;
  const btn = $("run-predict-btn");
  const text = $("briefing-text");
  const meta = $("briefing-meta");
  btn.disabled = true;
  btn.textContent = "생성 중... (20~40초)";
  text.textContent = "⏳ Gemini 호출 중...\n(무료 티어는 최대 60초 소요)";
  meta.textContent = "";
  try {
    const slot = state.slot;
    const res = await api(`/api/predict/run?slot=${slot}`, { method: "POST" });
    if (res && res.ok) {
      toast("✅ 새 브리핑 생성 완료");
      // 생성 직후 즉시 캐시 갱신 + 화면 갱신
      const fresh = { slot, text: res.text, ts: new Date().toISOString() };
      cacheSet(`briefing_${slot}`, fresh);
      renderBriefingData(fresh, slot, false);
    }
  } catch (e) {
    // 에러를 브리핑 영역에 크게 표시 (폰에서 toast만 뜨면 놓치기 쉬움)
    const body = e.body || {};
    if (e.status === 429 || body.reason === "quota_exhausted") {
      text.textContent = body.user_message ||
        "⚠️ Gemini 무료 쿼터 소진. 1~2시간 후 재시도하거나 결제 연결 필요.";
      meta.textContent = "quota_exhausted · " + new Date().toLocaleString("ko-KR");
    } else {
      text.textContent = "❌ 생성 실패\n\n" +
        (body.user_message || e.message || "알 수 없는 오류") +
        (body.type ? `\n\n[${body.type}]` : "");
      meta.textContent = "error · " + new Date().toLocaleString("ko-KR");
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "🤖 지금 새 브리핑 생성 (Gemini 호출)";
  }
});

// ── 관심종목 ───────────────────────────────
function renderWatchlistData(data) {
  const list = $("watchlist-list");
  state.watchlist = data.items || [];
  list.innerHTML = "";
  if (!state.watchlist.length) {
    list.innerHTML = '<div class="empty">관심종목이 없습니다.<br>위 검색창에서 추가해보세요.</div>';
    return;
  }
  state.watchlist.forEach((s) => {
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

async function loadWatchlist() {
  const list = $("watchlist-list");
  const cached = cacheGet("watchlist");
  if (cached && cached.data) {
    renderWatchlistData(cached.data);
  } else {
    list.innerHTML = '<div class="loading">로딩중...</div>';
  }
  try {
    const data = await api("/api/watchlist");
    cacheSet("watchlist", data);
    renderWatchlistData(data);
  } catch (e) {
    if (!cached) {
      list.innerHTML = '<div class="empty">서버 연결 실패. 잠시 후 새로고침(↻).</div>';
    }
  }
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
// 사용자가 예측 탭 안 열어도 미리 캐시에 받아두기 (다음에 열 때 즉시 표시)
(async () => {
  try {
    const data = await api(`/api/briefing/realtime`);
    cacheSet(`briefing_realtime`, data);
  } catch {}
})();
