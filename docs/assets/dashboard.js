const files = {
  quarterly: "data/quarterly_top10.csv",
  yearly30: "data/single_movie_over_30_year_summary.csv",
  movie30: "data/single_movie_over_30_movie_summary.csv",
  daily30: "data/single_movie_over_30_daily_summary.csv",
  events30: "data/single_movie_over_30_daily_events.csv",
  periods30: "data/single_movie_over_30_periods.csv",
  concentration: "data/group_60_70_periods.csv",
};

const state = {
  data: {},
  charts: {},
};

Chart.defaults.font.family =
  '"Malgun Gothic", "Apple SD Gothic Neo", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
Chart.defaults.color = "#334155";

function parseCsv(text) {
  const rows = [];
  let row = [];
  let value = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"') {
      if (inQuotes && next === '"') {
        value += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      row.push(value);
      value = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") i += 1;
      row.push(value);
      if (row.some((cell) => cell !== "")) rows.push(row);
      row = [];
      value = "";
    } else {
      value += char;
    }
  }

  if (value || row.length) {
    row.push(value);
    rows.push(row);
  }

  const [headers, ...body] = rows;
  return body.map((cells) =>
    Object.fromEntries(headers.map((header, index) => [header, cells[index] ?? ""])),
  );
}

async function loadCsv(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} 파일을 불러오지 못했습니다.`);
  return parseCsv(await response.text());
}

function number(value) {
  const parsed = Number(String(value ?? "").replaceAll(",", ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatPercent(value) {
  return `${number(value).toFixed(1)}%`;
}

function formatDays(value) {
  return `${Math.round(number(value)).toLocaleString("ko-KR")}일`;
}

function hashColor(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = text.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 66%, 45%)`;
}

function setOptions(select, values) {
  select.innerHTML = values.map((value) => `<option value="${value}">${value}</option>`).join("");
}

function destroyChart(id) {
  if (state.charts[id]) {
    state.charts[id].destroy();
  }
}

function activateTabs() {
  const tabs = document.querySelectorAll(".tab");
  const panels = document.querySelectorAll(".panel");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((item) => item.classList.remove("active"));
      panels.forEach((panel) => panel.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(tab.dataset.panel).classList.add("active");
    });
  });
}

function renderKpis() {
  const yearly = state.data.yearly30;
  const movies = state.data.movie30;
  const periods = state.data.periods30;

  const totalDays = yearly.reduce(
    (sum, row) => sum + number(row.days_with_any_movie_over_threshold),
    0,
  );
  const longest = [...periods].sort((a, b) => number(b.days) - number(a.days))[0];
  const peak = [...movies].sort((a, b) => number(b.max_share) - number(a.max_share))[0];

  document.getElementById("kpi-days").textContent = formatDays(totalDays);
  document.getElementById("kpi-movies").textContent = `${movies.length.toLocaleString("ko-KR")}편`;
  document.getElementById("kpi-longest").textContent = longest
    ? `${longest.movie_nm} ${formatDays(longest.days)}`
    : "-";
  document.getElementById("kpi-peak").textContent = peak
    ? `${peak.movie_nm} ${formatPercent(peak.max_share)}`
    : "-";
}

function renderYearlyDaysChart() {
  destroyChart("yearlyDaysChart");
  const rows = state.data.yearly30.sort((a, b) => number(a.year) - number(b.year));
  state.charts.yearlyDaysChart = new Chart(document.getElementById("yearlyDaysChart"), {
    type: "bar",
    data: {
      labels: rows.map((row) => row.year),
      datasets: [
        {
          label: "발생일수",
          data: rows.map((row) => number(row.days_with_any_movie_over_threshold)),
          backgroundColor: "#2a9d8f",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { callback: (value) => `${value}일` } } },
    },
  });
}

function renderTopMoviesChart() {
  destroyChart("topMoviesChart");
  const rows = state.data.movie30
    .slice()
    .sort((a, b) => number(b.days_over_threshold) - number(a.days_over_threshold))
    .slice(0, 15)
    .reverse();

  state.charts.topMoviesChart = new Chart(document.getElementById("topMoviesChart"), {
    type: "bar",
    data: {
      labels: rows.map((row) => row.movie_nm),
      datasets: [
        {
          label: "30% 이상 발생일수",
          data: rows.map((row) => number(row.days_over_threshold)),
          backgroundColor: rows.map((row) => hashColor(row.movie_nm)),
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => `${context.raw}일`,
          },
        },
      },
      scales: { x: { beginAtZero: true, ticks: { callback: (value) => `${value}일` } } },
    },
  });
}

function initQuarterControls() {
  const years = [...new Set(state.data.quarterly.map((row) => row.quarter.slice(0, 4)))].sort();
  setOptions(document.getElementById("quarterYear"), years);
  updateQuarterOptions();
  document.getElementById("quarterYear").addEventListener("change", () => {
    updateQuarterOptions();
    renderQuarterChart();
  });
  document.getElementById("quarterSelect").addEventListener("change", renderQuarterChart);
}

function updateQuarterOptions() {
  const year = document.getElementById("quarterYear").value;
  const quarters = [
    ...new Set(
      state.data.quarterly
        .filter((row) => row.quarter.startsWith(year))
        .map((row) => row.quarter),
    ),
  ].sort();
  setOptions(document.getElementById("quarterSelect"), quarters);
}

function renderQuarterChart() {
  destroyChart("quarterChart");
  const quarter = document.getElementById("quarterSelect").value;
  const rows = state.data.quarterly
    .filter((row) => row.quarter === quarter)
    .sort((a, b) => number(b.quarter_screen_share) - number(a.quarter_screen_share))
    .reverse();

  state.charts.quarterChart = new Chart(document.getElementById("quarterChart"), {
    type: "bar",
    data: {
      labels: rows.map((row) => row.movie_nm),
      datasets: [
        {
          label: "분기 스크린 점유율",
          data: rows.map((row) => number(row.quarter_screen_share)),
          backgroundColor: rows.map((row) => hashColor(row.movie_nm)),
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => formatPercent(context.raw),
          },
        },
      },
      scales: { x: { beginAtZero: true, ticks: { callback: (value) => `${value}%` } } },
    },
  });
}

function initSingleControls() {
  const years = [...new Set(state.data.daily30.map((row) => row.year))].sort();
  setOptions(document.getElementById("singleYear"), years);
  document.getElementById("singleYear").addEventListener("change", () => {
    renderSingleTimeline();
    renderPeriodTable();
  });
  document.getElementById("movieSearch").addEventListener("input", renderPeriodTable);
}

function renderSingleTimeline() {
  destroyChart("singleTimelineChart");
  const year = document.getElementById("singleYear").value;
  const rows = state.data.daily30.filter((row) => row.year === year).sort((a, b) => a.date.localeCompare(b.date));

  state.charts.singleTimelineChart = new Chart(document.getElementById("singleTimelineChart"), {
    type: "line",
    data: {
      labels: rows.map((row) => row.date),
      datasets: [
        {
          label: "해당일 최대 단일 점유율",
          data: rows.map((row) => number(row.max_single_share)),
          borderColor: "#123047",
          pointBackgroundColor: rows.map((row) => hashColor(row.top_movie)),
          pointBorderColor: rows.map((row) => hashColor(row.top_movie)),
          pointRadius: 4,
          pointHoverRadius: 7,
          borderWidth: 1.5,
          tension: 0.18,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => items[0].label,
            label: (context) => {
              const row = rows[context.dataIndex];
              return `${row.top_movie}: ${formatPercent(row.max_single_share)}`;
            },
          },
        },
      },
      scales: {
        y: { min: 25, ticks: { callback: (value) => `${value}%` } },
        x: { ticks: { maxTicksLimit: 12 } },
      },
    },
  });
}

function renderPeriodTable() {
  const year = document.getElementById("singleYear").value;
  const query = document.getElementById("movieSearch").value.trim().toLowerCase();
  const tbody = document.getElementById("periodTable");
  const rows = state.data.periods30
    .filter((row) => row.start_date.startsWith(year) || row.end_date.startsWith(year))
    .filter((row) => !query || row.movie_nm.toLowerCase().includes(query))
    .sort((a, b) => number(b.days) - number(a.days))
    .slice(0, 60);

  tbody.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td>${row.movie_nm}</td>
          <td>${row.start_date}</td>
          <td>${row.end_date}</td>
          <td>${formatDays(row.days)}</td>
          <td>${formatPercent(row.max_share)}</td>
        </tr>
      `,
    )
    .join("");
}

function initConcentrationControls() {
  const years = [
    ...new Set(
      state.data.concentration.flatMap((row) => [
        row.start_date.slice(0, 4),
        row.end_date.slice(0, 4),
      ]),
    ),
  ].sort();
  setOptions(document.getElementById("concentrationYear"), years);
  document
    .getElementById("concentrationYear")
    .addEventListener("change", renderConcentrationChart);
  document
    .getElementById("concentrationThreshold")
    .addEventListener("change", renderConcentrationChart);
}

function periodIntersectsYear(row, year) {
  const start = new Date(row.start_date);
  const end = new Date(row.end_date);
  const yearStart = new Date(`${year}-01-01`);
  const yearEnd = new Date(`${year}-12-31`);
  return start <= yearEnd && end >= yearStart;
}

function shortMovies(value) {
  const text = value || "";
  return text.length > 34 ? `${text.slice(0, 34)}...` : text;
}

function renderConcentrationChart() {
  destroyChart("concentrationChart");
  const year = document.getElementById("concentrationYear").value;
  const threshold = document.getElementById("concentrationThreshold").value;
  const rows = state.data.concentration
    .filter((row) => periodIntersectsYear(row, year))
    .filter((row) => threshold === "all" || row.threshold === threshold)
    .sort((a, b) => a.start_date.localeCompare(b.start_date))
    .slice(0, 30);

  state.charts.concentrationChart = new Chart(document.getElementById("concentrationChart"), {
    type: "bar",
    data: {
      labels: rows.map((row) => [
        `${row.start_date.slice(5)}~${row.end_date.slice(5)}`,
        shortMovies(row.representative_movies),
      ]),
      datasets: [
        {
          label: "연속일수",
          data: rows.map((row) => number(row.days)),
          yAxisID: "y",
          backgroundColor: rows.map((row) =>
            row.threshold === "70% 이상" ? "rgba(231, 111, 81, 0.82)" : "rgba(42, 157, 143, 0.82)",
          ),
        },
        {
          type: "line",
          label: "기간 내 최고 점유율",
          data: rows.map((row) => number(row.max_share)),
          yAxisID: "y1",
          borderColor: "#123047",
          backgroundColor: "#123047",
          pointRadius: 4,
          pointHoverRadius: 7,
          borderWidth: 2,
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top" },
        tooltip: {
          callbacks: {
            title: (items) => rows[items[0].dataIndex].representative_movies,
            label: (context) => {
              const row = rows[context.dataIndex];
              if (context.dataset.type === "line") {
                return `최고 점유율: ${formatPercent(row.max_share)}`;
              }
              return `${row.threshold}, ${formatDays(row.days)}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: {
            maxRotation: 55,
            minRotation: 35,
            autoSkip: false,
            font: { size: 10 },
          },
        },
        y: {
          beginAtZero: true,
          position: "left",
          title: { display: true, text: "연속일수" },
          ticks: { callback: (value) => `${value}일` },
        },
        y1: {
          beginAtZero: true,
          position: "right",
          title: { display: true, text: "최고 점유율" },
          grid: { drawOnChartArea: false },
          ticks: { callback: (value) => `${value}%` },
        },
      },
    },
  });
}

async function init() {
  activateTabs();
  const entries = await Promise.all(
    Object.entries(files).map(async ([key, path]) => [key, await loadCsv(path)]),
  );
  state.data = Object.fromEntries(entries);

  renderKpis();
  renderYearlyDaysChart();
  renderTopMoviesChart();
  initQuarterControls();
  renderQuarterChart();
  initSingleControls();
  renderSingleTimeline();
  renderPeriodTable();
  initConcentrationControls();
  renderConcentrationChart();
}

init().catch((error) => {
  document.querySelector("main").innerHTML = `
    <article class="card">
      <div class="card-head"><h2>데이터를 불러오지 못했습니다</h2></div>
      <div class="table-wrap"><p style="padding: 16px; line-height: 1.7;">${error.message}</p></div>
    </article>
  `;
});
