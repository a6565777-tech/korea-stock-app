// ── 기본 설정 ───────────────────────────────
// 같은 도메인에서 서빙되면 빈 문자열, 아니면 Vercel URL 직접 지정
const API = window.location.origin;

// ── 상태 ───────────────────────────────────
// 마지막으로 본 탭/슬롯을 localStorage에서 복원 (앱 재실행 시 그 위치로 바로)
const _lastUI = (() => {
  try {
    const raw = localStorage.getItem("stockapp_ui_v1");
    return raw ? JSON.parse(raw) : {};
  } catch { return {}; }
})();
let state = {
  tab: _lastUI.tab || "positions",
  slot: _lastUI.slot || "realtime",
  watchlist: [],
};
function saveUIState() {
  try {
    localStorage.setItem("stockapp_ui_v1", JSON.stringify({ tab: state.tab, slot: state.slot }));
  } catch {}
}

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
function activateTab(t) {
  document.querySelectorAll(".tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === t);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  const panel = $("tab-" + t);
  if (panel) panel.classList.add("active");
  state.tab = t;
  saveUIState();
  if (t === "positions") loadPositions();
  if (t === "predict") loadBriefing(state.slot);
  if (t === "watchlist") loadWatchlist();
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

// 앱 시작 시: 저장된 마지막 탭으로 복원 (기본값: positions)
activateTab(state.tab);

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

function _projRow(label, proj) {
  // label: "목표" or "손절", proj: {price, gross_pnl, gross_pct, net_pnl, net_pct, total_fees}
  if (!proj) return "";
  const icon = label === "목표" ? "🎯" : "🛑";
  return `
    <div class="proj-block">
      <div class="proj-title">${icon} ${label} ${fmtWon(proj.price)} 도달 시</div>
      <div class="proj-line">
        <span>수수료 전</span>
        <b class="${pnlClass(proj.gross_pnl)}">${fmtWon(proj.gross_pnl)} (${fmtPct(proj.gross_pct)})</b>
      </div>
      <div class="proj-line">
        <span>수수료·세금 후 <span class="dim">(-${fmtWon(proj.total_fees)})</span></span>
        <b class="${pnlClass(proj.net_pnl)}">${fmtWon(proj.net_pnl)} (${fmtPct(proj.net_pct)})</b>
      </div>
    </div>
  `;
}

function renderPosition(p) {
  const div = document.createElement("div");
  div.className = "position-card";
  const target = p.target_hit ? '<span class="badge badge-target">🎯 목표도달</span>' : "";
  const stop = p.stop_hit ? '<span class="badge badge-stop">🛑 손절도달</span>' : "";
  // 본전 알림 (현재가 < 본전이면 "본전까지 +X원" 표시)
  let breakevenHint = "";
  if (p.breakeven && p.current_price) {
    const diff = p.breakeven - p.current_price;
    const diffPct = (diff / p.current_price) * 100;
    if (diff > 0) {
      breakevenHint = `<div class="row"><span>본전 가격 <span class="dim">(수수료 포함)</span></span><b class="dim">${fmtWon(p.breakeven)} (현재보다 +${diffPct.toFixed(2)}%)</b></div>`;
    } else {
      breakevenHint = `<div class="row"><span>본전 가격 <span class="dim">(수수료 포함)</span></span><b class="pnl-positive">돌파 ✓ ${fmtWon(p.breakeven)}</b></div>`;
    }
  }
  div.innerHTML = `
    <button class="del-btn" data-code="${p.code}">✕</button>
    <div class="name">${p.name}${target}${stop}</div>
    <div class="code">${p.code} · ${p.quantity}주 @ ${fmtWon(p.buy_price)}</div>
    <div class="row"><span>현재가</span><b>${fmtWon(p.current_price)} <span class="${pnlClass(p.change_pct)}" style="font-size:12px">(${fmtPct(p.change_pct)} 일간)</span></b></div>
    <div class="row"><span>평가액</span><b>${fmtWon(p.current_value)}</b></div>
    ${breakevenHint}
    ${p.note ? `<div class="row"><span>메모</span><b style="font-size:12px;font-weight:400">${p.note}</b></div>` : ""}
    <div class="pnl-bar">
      <div class="pnl-net-label">실손익 <span class="dim">(수수료·세금 반영)</span></div>
      <div class="pnl-net ${pnlClass(p.net_pnl)}">${fmtWon(p.net_pnl)} <span class="pnl-net-pct">(${fmtPct(p.net_pct)})</span></div>
      <div class="pnl-gross-row">
        <span class="dim">장부상 (수수료 전)</span>
        <span class="${pnlClass(p.pnl_amount)}">${fmtWon(p.pnl_amount)} (${fmtPct(p.pnl_pct)})</span>
      </div>
    </div>
    ${_projRow("목표", p.target_projection)}
    ${_projRow("손절", p.stop_projection)}
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

function activateSlot(s) {
  document.querySelectorAll(".slot-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.slot === s);
  });
  state.slot = s;
  saveUIState();
  updateBriefingControls(s);
  loadBriefing(s);
}

document.querySelectorAll(".slot-btn").forEach((btn) => {
  btn.addEventListener("click", () => activateSlot(btn.dataset.slot));
});

// 초기 로드: 저장된 슬롯으로 복원 (HTML 기본은 realtime이 active지만 state가 다르면 갱신)
document.querySelectorAll(".slot-btn").forEach((b) => {
  b.classList.toggle("active", b.dataset.slot === state.slot);
});
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
  // 1. 캐시 즉시 표시 (내용이 있을 때만 — 빈 캐시는 무시하고 서버 응답 대기)
  const cached = cacheGet(cacheKey);
  const hasLocalText = !!(cached && cached.data && cached.data.text);
  if (hasLocalText) {
    renderBriefingData(cached.data, slot, true);
  } else {
    text.textContent = "로딩중...";
    meta.textContent = "";
  }
  // 2. 백그라운드로 최신 데이터
  try {
    const data = await api(`/api/briefing/${slot}`);
    const serverHasText = !!(data && data.text);

    // 서버가 빈 응답인데 로컬에 이전 기록이 있다면 → 로컬 유지 (덮어쓰지 않음)
    // 이유: 앱을 다시 켜도 "마지막 불러온 기록"이 그대로 보이게.
    if (!serverHasText && hasLocalText) {
      // 화면은 이미 캐시로 렌더됨. 추가 작업 없음.
      return;
    }

    // 서버에 새로운 내용이 있음 → 캐시·화면 모두 갱신
    // 또는 둘 다 비었음 → 빈 상태 안내 메시지 표시
    cacheSet(cacheKey, data);
    renderBriefingData(data, slot, false);
  } catch (e) {
    // 서버 실패: 로컬 캐시가 있으면 그대로 두고, 없을 때만 에러 안내
    if (!hasLocalText) {
      text.textContent = "서버 연결 실패. 잠시 후 새로고침(↻).";
    }
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

// ── 공통 새로고침 ───────────────────────────
// 현재 탭에 맞는 데이터 로더를 Promise로 반환. PTR/버튼 양쪽에서 재사용.
function refreshCurrentTab() {
  if (state.tab === "positions") return loadPositions();
  if (state.tab === "predict") return loadBriefing(state.slot);
  if (state.tab === "watchlist") return loadWatchlist();
  return Promise.resolve();
}

// ── 상단 새로고침 ───────────────────────────
$("refresh-btn").addEventListener("click", () => {
  refreshCurrentTab();
  toast("새로고침");
});

// ── Pull-to-refresh ────────────────────────
// 페이지 최상단에서 아래로 드래그하면 리프레시. iOS 바운스와 충돌 피하려고
// scrollY===0 일 때만 시작. 모달 떠있으면 스킵.
(() => {
  const THRESHOLD = 70;      // 이 이상 당겨야 새로고침 발동
  const MAX_PULL = 120;      // 시각적 최대 당김 거리
  const RESIST = 0.5;        // 저항 계수 (손가락 이동 거리의 절반만 내려옴)

  // 인디케이터 DOM 생성 (HTML 안 건드리려고 JS에서 주입)
  const ptr = document.createElement("div");
  ptr.id = "ptr";
  ptr.innerHTML = '<span class="ptr-icon">↓</span>';
  document.body.appendChild(ptr);
  const icon = ptr.querySelector(".ptr-icon");

  let startY = null;
  let pulling = false;
  let refreshing = false;

  function modalOpen() {
    return !$("add-modal").classList.contains("hidden");
  }

  function setPull(distance) {
    const y = Math.min(distance, MAX_PULL) - 60;   // -60 = 숨김 위치
    ptr.style.transform = `translateY(${y}px)`;
    // 70% 이상 당기면 화살표를 ↑로 바꿔서 "놓으면 새로고침" 힌트
    const ratio = distance / THRESHOLD;
    if (ratio >= 1) {
      icon.style.transform = "rotate(180deg)";
    } else {
      icon.style.transform = `rotate(${ratio * 180}deg)`;
    }
  }

  function reset() {
    pulling = false;
    startY = null;
    ptr.classList.remove("dragging");
    ptr.style.transform = "";
    icon.style.transform = "";
  }

  document.addEventListener("touchstart", (e) => {
    if (refreshing || modalOpen()) return;
    if (window.scrollY > 0) return;   // 이미 스크롤 내려가 있으면 PTR 안 함
    if (e.touches.length !== 1) return;
    startY = e.touches[0].clientY;
    pulling = false;
  }, { passive: true });

  document.addEventListener("touchmove", (e) => {
    if (startY == null || refreshing) return;
    const dy = e.touches[0].clientY - startY;
    if (dy <= 0) {
      // 위로 스와이프하거나 제자리 — PTR 중단
      if (pulling) reset();
      return;
    }
    // 아래로 드래그. scrollY === 0 이어야만 PTR 상태 진입.
    if (window.scrollY > 0) {
      reset();
      return;
    }
    if (!pulling) {
      pulling = true;
      ptr.classList.add("dragging");
    }
    const distance = dy * RESIST;
    setPull(distance);
    // 저항 걸고 나서도 충분히 내려왔으면 기본 스크롤 막음 (iOS 바운스 방지)
    if (distance > 10 && e.cancelable) e.preventDefault();
  }, { passive: false });

  document.addEventListener("touchend", async () => {
    if (!pulling || refreshing) {
      if (pulling) reset();
      return;
    }
    // 마지막 translateY 계산: 현재 transform 파싱 대신, 당긴 거리 재계산
    // 간단히 transform 스타일에서 Y 추출
    const m = /translateY\((-?\d+(?:\.\d+)?)px\)/.exec(ptr.style.transform);
    const currentY = m ? parseFloat(m[1]) : -60;
    const pulledDistance = currentY + 60;   // 보이는 정도

    ptr.classList.remove("dragging");

    if (pulledDistance >= THRESHOLD) {
      // 새로고침 발동
      refreshing = true;
      ptr.classList.add("refreshing");
      ptr.style.transform = "";   // CSS 의 translateY(0) 으로
      try {
        await refreshCurrentTab();
        toast("새로고침됨");
      } catch {
        toast("새로고침 실패");
      } finally {
        ptr.classList.remove("refreshing");
        refreshing = false;
        reset();
      }
    } else {
      // 임계치 미달 — 원복
      reset();
    }
  }, { passive: true });
})();

// ── Service Worker 등록 (PWA) ──────────────
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    // updateViaCache: 'none' → SW 파일 자체를 HTTP 캐시 거치지 않고 항상 네트워크로 받음.
    // 배포 후 재실행 1번만에 새 SW 감지되도록.
    navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" })
      .then((reg) => {
        // 앱 열 때마다 업데이트 체크
        reg.update().catch(() => {});
      })
      .catch((e) => console.warn("SW 등록 실패", e));
  });
  // 새 SW 가 활성화되면 현재 페이지도 1회만 리로드 → 새 JS/CSS 즉시 반영.
  let _reloadedForSW = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (_reloadedForSW) return;
    _reloadedForSW = true;
    window.location.reload();
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
