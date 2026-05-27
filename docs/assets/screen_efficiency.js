(() => {
const effState = {
  charts: {},
  daily: screenEfficiencyDashboardData.daily || [],
  summary: screenEfficiencyDashboardData.movieSummary || [],
};

Chart.defaults.font.family =
  '"Malgun Gothic", "Apple SD Gothic Neo", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
Chart.defaults.color = "#334155";

function n(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function pct(value, digits = 1) {
  const parsed = n(value);
  return parsed === null ? "-" : `${parsed.toFixed(digits)}%`;
}

function count(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("ko-KR") : "-";
}

function ratio(value, digits = 2) {
  const parsed = n(value);
  return parsed === null ? "-" : parsed.toFixed(digits);
}

function shortName(name) {
  return String(name || "").replace("미션 임파서블: 데드 레코닝 PART ONE", "미션 임파서블").replace("블랙 팬서: 와칸다 포에버", "블랙 팬서");
}

function destroyChart(id) {
  if (effState.charts[id]) effState.charts[id].destroy();
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function validRows(rows, key) {
  return rows.filter((row) => n(row[key]) !== null);
}

function renderKpis() {
  const summary = effState.summary;
  const peak = validRows(summary, "peak_SS_screen_share_pct").sort(
    (a, b) => n(b.peak_SS_screen_share_pct) - n(a.peak_SS_screen_share_pct),
  )[0];
  const mii = validRows(summary, "mean_MII_pct").sort((a, b) => n(b.mean_MII_pct) - n(a.mean_MII_pct))[0];
  const coverage =
    summary.reduce((sum, row) => sum + Number(row.seat_data_days || 0), 0) /
    Math.max(1, summary.reduce((sum, row) => sum + Number(row.observed_days || 0), 0));

  setText("eff-kpi-movies", `${summary.length.toLocaleString("ko-KR")}편`);
  setText("eff-kpi-peak", peak ? `${shortName(peak.movie_nm)} ${pct(peak.peak_SS_screen_share_pct)}` : "-");
  setText("eff-kpi-mii", mii ? `${shortName(mii.movie_nm)} ${pct(mii.mean_MII_pct)}` : "-");
  setText("eff-kpi-coverage", `${(coverage * 100).toFixed(1)}%`);
}

function renderInsights() {
  const summary = effState.summary;
  const peak = validRows(summary, "peak_SS_screen_share_pct").sort(
    (a, b) => n(b.peak_SS_screen_share_pct) - n(a.peak_SS_screen_share_pct),
  )[0];
  const efficient = validRows(summary, "mean_ScEI_screen_efficiency").sort(
    (a, b) => n(b.mean_ScEI_screen_efficiency) - n(a.mean_ScEI_screen_efficiency),
  )[0];
  const inefficient = validRows(summary, "mean_MII_pct").sort((a, b) => n(b.mean_MII_pct) - n(a.mean_MII_pct))[0];
  const lowCoverage = summary
    .map((row) => ({
      ...row,
      coverage: Number(row.seat_data_days || 0) / Math.max(1, Number(row.observed_days || 0)),
    }))
    .sort((a, b) => a.coverage - b.coverage)[0];

  const items = [
    peak
      ? `<span class="badge">SS</span><b>${peak.movie_nm}</b>의 최고 스크린 점유율이 <b>${pct(peak.peak_SS_screen_share_pct)}</b>로 가장 높았습니다. 이 시점은 스크린 배정이 특정 영화에 가장 집중된 날입니다.`
      : "",
    efficient
      ? `<span class="badge">ScEI</span><b>${efficient.movie_nm}</b>은 평균 ScEI가 <b>${ratio(efficient.mean_ScEI_screen_efficiency)}</b>로 높아, 스크린 배정 대비 관객 동원이 상대적으로 강한 편입니다.`
      : "",
    inefficient
      ? `<span class="badge">MII</span><b>${inefficient.movie_nm}</b>은 평균 MII가 <b>${pct(inefficient.mean_MII_pct)}</b>로 높아, 스크린 집중과 좌석판매율의 균형을 함께 점검할 필요가 있습니다.`
      : "",
    lowCoverage
      ? `<span class="badge">자료</span>좌석 데이터 커버리지가 가장 낮은 영화는 <b>${lowCoverage.movie_nm}</b>입니다. 관측일 중 좌석 데이터가 붙은 날은 <b>${(lowCoverage.coverage * 100).toFixed(1)}%</b>입니다.`
      : "",
  ].filter(Boolean);

  document.getElementById("eff-insights").innerHTML = items.map((item) => `<li>${item}</li>`).join("");
}

function efficiencyLabel(row) {
  const scei = n(row.mean_ScEI_screen_efficiency);
  const mii = n(row.mean_MII_pct);
  if (scei === null) return "좌석 데이터가 부족해 효율 판단을 보류해야 합니다.";
  if (scei >= 1.1 && (mii === null || mii < 15)) {
    return "관객 점유율이 스크린 점유율보다 높아 스크린 배정 대비 관객 효율이 비교적 높은 편입니다.";
  }
  if (scei < 0.8 && mii !== null && mii >= 15) {
    return "스크린 배정 강도에 비해 관객 효율이 낮고, 좌석 미판매분까지 함께 나타난 구간이 있습니다.";
  }
  if (mii !== null && mii >= 20) {
    return "스크린 집중과 낮은 좌석판매율이 함께 관측되어 좌석 활용 측면의 점검이 필요합니다.";
  }
  return "스크린 집중과 관객 효율이 중간 수준으로 관측됩니다.";
}

function coverageLabel(row) {
  const observed = Number(row.observed_days || 0);
  const seatDays = Number(row.seat_data_days || 0);
  const coverage = observed ? (seatDays / observed) * 100 : 0;
  if (coverage < 30) return `좌석 데이터 커버리지는 ${coverage.toFixed(1)}%로 낮아 해석에 주의가 필요합니다.`;
  if (coverage < 60) return `좌석 데이터 커버리지는 ${coverage.toFixed(1)}%로 일부 기간 중심의 해석입니다.`;
  return `좌석 데이터 커버리지는 ${coverage.toFixed(1)}%입니다.`;
}

function renderMovieDetail(movie) {
  const row = effState.summary.find((item) => item.movie_nm === movie);
  const container = document.getElementById("movieDetail");
  if (!row) {
    container.innerHTML = "<p>선택한 영화의 요약 데이터가 없습니다.</p>";
    return;
  }

  const period =
    row.over_30_period_start && row.over_30_period_end
      ? `${row.over_30_period_start}~${row.over_30_period_end}`
      : "30% 초과 기간 정보 없음";

  container.innerHTML = `
    <h3>${row.movie_nm}</h3>
    <div class="detail-grid">
      <div><span>최고 SS</span><b>${pct(row.peak_SS_screen_share_pct)}</b></div>
      <div><span>최고일</span><b>${row.peak_screen_share_date || "-"}</b></div>
      <div><span>평균 ScEI</span><b>${ratio(row.mean_ScEI_screen_efficiency)}</b></div>
      <div><span>평균 MII</span><b>${pct(row.mean_MII_pct)}</b></div>
      <div><span>관측일</span><b>${count(row.observed_days)}일</b></div>
      <div><span>좌석 데이터</span><b>${count(row.seat_data_days)}일</b></div>
    </div>
    <p><b>30% 초과 구간:</b> ${period}</p>
    <p><b>객관적 해석:</b> ${efficiencyLabel(row)}</p>
    <p><b>자료 신뢰도:</b> ${coverageLabel(row)} 이 평가는 KOBIS 기반 산출 데이터에 한정하며, 좌석 데이터가 없는 날짜는 효율 지표에 반영되지 않습니다.</p>
  `;
}

function renderEfficiencyBar() {
  destroyChart("efficiencyBarChart");
  const rows = [...effState.summary].sort((a, b) => n(b.peak_SS_screen_share_pct) - n(a.peak_SS_screen_share_pct));
  const ctx = document.getElementById("efficiencyBarChart");
  effState.charts.efficiencyBarChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: rows.map((row) => shortName(row.movie_nm)),
      datasets: [
        {
          label: "최고 스크린 점유율",
          data: rows.map((row) => n(row.peak_SS_screen_share_pct)),
          backgroundColor: "#2F6F9F",
          yAxisID: "y",
        },
        {
          label: "평균 ScEI",
          data: rows.map((row) => n(row.mean_ScEI_screen_efficiency)),
          borderColor: "#E76F51",
          backgroundColor: "#E76F51",
          type: "line",
          yAxisID: "y1",
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "스크린 점유율(%)" } },
        y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "ScEI" } },
      },
    },
  });
}

function renderMiiScatter() {
  destroyChart("miiScatterChart");
  const rows = validRows(effState.summary, "mean_MII_pct");
  const ctx = document.getElementById("miiScatterChart");
  effState.charts.miiScatterChart = new Chart(ctx, {
    type: "scatter",
    data: {
      datasets: [
        {
          label: "영화",
          data: rows.map((row) => ({
            x: n(row.mean_SS_screen_share_pct),
            y: n(row.mean_MII_pct),
            movie: row.movie_nm,
          })),
          pointRadius: 6,
          pointHoverRadius: 8,
          backgroundColor: "#55A99A",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        tooltip: {
          callbacks: {
            label: (context) => `${context.raw.movie}: SS ${pct(context.raw.x)}, MII ${pct(context.raw.y)}`,
          },
        },
      },
      scales: {
        x: { beginAtZero: true, title: { display: true, text: "평균 스크린 점유율(%)" } },
        y: { beginAtZero: true, title: { display: true, text: "평균 MII(%)" } },
      },
    },
  });
}

function initMovieSelect() {
  const select = document.getElementById("effMovieSelect");
  select.innerHTML = effState.summary.map((row) => `<option value="${row.movie_nm}">${row.movie_nm}</option>`).join("");
  select.addEventListener("change", () => {
    renderMovieDetail(select.value);
    renderDailyChart(select.value);
  });
  const initialMovie = select.value || effState.summary[0]?.movie_nm;
  renderMovieDetail(initialMovie);
  renderDailyChart(initialMovie);
}

function renderDailyChart(movie) {
  destroyChart("dailyEfficiencyChart");
  const rows = effState.daily.filter((row) => row.movie_nm === movie && row.has_seat_data);
  const ctx = document.getElementById("dailyEfficiencyChart");
  effState.charts.dailyEfficiencyChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: rows.map((row) => row.date),
      datasets: [
        { label: "SS", data: rows.map((row) => n(row.SS_screen_share_pct)), borderColor: "#2F6F9F", tension: 0.25 },
        { label: "좌석판매율", data: rows.map((row) => n(row.seat_sales_rate_pct)), borderColor: "#55A99A", tension: 0.25 },
        { label: "MII", data: rows.map((row) => n(row.MII_pct)), borderColor: "#E76F51", tension: 0.25 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { beginAtZero: true, title: { display: true, text: "%" } } },
    },
  });
}

function renderSummaryTable() {
  const rows = [...effState.summary].sort((a, b) => n(b.peak_SS_screen_share_pct) - n(a.peak_SS_screen_share_pct));
  document.getElementById("effSummaryTable").innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td>${row.movie_nm}</td>
          <td>${pct(row.peak_SS_screen_share_pct)}</td>
          <td>${ratio(row.mean_ScEI_screen_efficiency)}</td>
          <td>${pct(row.mean_MII_pct)}</td>
          <td>${row.interpretation || "-"}</td>
        </tr>
      `,
    )
    .join("");
}

let booted = false;

function boot() {
  if (booted) return;
  booted = true;
  renderKpis();
  renderInsights();
  renderEfficiencyBar();
  renderMiiScatter();
  renderSummaryTable();
  initMovieSelect();
}

const efficiencyTab = document.querySelector('[data-panel="efficiency"]');
if (efficiencyTab) {
  efficiencyTab.addEventListener("click", () => {
    window.setTimeout(boot, 0);
  });
} else {
  boot();
}
})();
