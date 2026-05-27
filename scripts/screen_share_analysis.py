"""
KOBIS 일별 박스오피스 API — 스크린 점유율 분석 (2020.01.01 ~ 오늘)

분석 항목:
  1. 분기(3개월)별 스크린 점유율 TOP10 (연도별 시각화)
  2. 상위 1~3개 영화 합산이 60% / 70% 이상인 기간 (연도별 시각화, 색상 구분)
  3. 단일 1위 영화가 40% / 50% 이상인 기간 (연도별 시각화, 색상 구분)
     - 50% 이상인 경우 관객수 등급 표시

관객수 등급 (50% 이상 단일 독점 / 60% 이상 합산 구간 공통):
  - 수집 기간 안에서 확인된 최대 누적 관객 기준입니다.
    현재 흥행 중인 영화는 최종 관객수보다 낮게 표시될 수 있습니다.
  🟣 보라  : 1,000만+ (천만 영화)
  🔴 빨강  : 900만+  (천만 근접)
  🟠 주황  : 500만+
  🔵 파랑  : 500만 미만

실행 예시:
  /home/yjm/data_journalism/test/.venv/bin/python screen_share_analysis.py
  /home/yjm/data_journalism/test/.venv/bin/python screen_share_analysis.py --start-date 2020-01-01 --force-refresh
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

try:
    import matplotlib.dates as mdates
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import pandas as pd
except ModuleNotFoundError as exc:
    raise SystemExit(
        "필요한 패키지가 없습니다.\n"
        "  /home/yjm/data_journalism/test/.venv/bin/pip install matplotlib pandas"
    ) from exc


# ── 상수 ─────────────────────────────────────────
BASE_URL = (
    "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/"
    "searchDailyBoxOfficeList.json"
)
DEFAULT_ENV_PATH   = Path("/home/yjm/data_journalism/test/.env")
DEFAULT_START_DATE = date(2020, 1, 1)
REQUEST_SLEEP_SEC  = 0.10   # API 호출 간격 (초)

# 관객수 등급: 수집 기간 내 최대 누적 관객 기준
TIER_RULES      = [
    (10_000_000, "1000만+"),
    (9_000_000,  "900만+"),
    (5_000_000,  "500만+"),
]
TIER_COLORS     = {
    "1000만+":  "#7B2D8B",   # 보라
    "900만+":   "#C0392B",   # 진빨강
    "500만+":   "#E67E22",   # 주황
    "500만미만": "#2980B9",   # 파랑
}
TIER_ALPHA = 0.35


# ── 데이터클래스 ──────────────────────────────────
@dataclass(frozen=True)
class AudienceTier:
    label: str
    marker: str


# ── CLI ───────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="KOBIS 스크린 점유율 분석")
    p.add_argument("--env-path",     default=str(DEFAULT_ENV_PATH))
    p.add_argument("--start-date",   default=DEFAULT_START_DATE.isoformat())
    p.add_argument("--end-date",     default=(date.today() - timedelta(days=1)).isoformat())
    p.add_argument("--output-dir",   default="kobis_screen_share_output")
    p.add_argument("--cache-dir",    default="kobis_api_cache")
    p.add_argument("--force-refresh", action="store_true")
    return p.parse_args()


# ── API 키 로드 ───────────────────────────────────
def load_api_key(env_path: Path) -> str:
    if not env_path.exists():
        raise FileNotFoundError(f".env 파일 없음: {env_path}")
    pattern = re.compile(r"^\s*KOBIS_API_KEY\s*=\s*(.+?)\s*$")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            val = m.group(1).strip().strip('"').strip("'")
            if val:
                return val
    raise ValueError(f"{env_path} 에 KOBIS_API_KEY 항목 없음")


# ── 유틸 ─────────────────────────────────────────
def to_int(v: Any) -> int:
    if v in (None, ""):
        return 0
    return int(str(v).replace(",", ""))


def daterange(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError(f"종료일({end})이 시작일({start})보다 빠릅니다.")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def get_tier(aud: int) -> str:
    for threshold, label in TIER_RULES:
        if aud >= threshold:
            return label
    return "500만미만"


def audience_tier(aud: int) -> AudienceTier:
    label = get_tier(aud)
    marker_map = {"1000만+": "10M+", "900만+": "9M+", "500만+": "5M+", "500만미만": "<5M"}
    return AudienceTier(label=label, marker=marker_map[label])


def audience_label(movie_nm: str, aud: int) -> str:
    t = audience_tier(aud)
    return f"{movie_nm} ({t.marker}, {aud:,}명)"


# ── 한글 폰트 ─────────────────────────────────────
def configure_korean_font() -> None:
    """설치된 폰트 중 한글 지원 폰트를 자동 탐지해 설정."""
    from matplotlib import font_manager as fm
    available = {f.name for f in fm.fontManager.ttflist}
    for font in ["AppleGothic", "NanumGothic", "NanumBarunGothic", "Malgun Gothic", "Gulim", "Dotum"]:
        if font in available:
            plt.rcParams["font.family"] = font
            break
    else:
        print("[경고] 한글 폰트 미발견 — 텍스트가 깨질 수 있습니다.")
    plt.rcParams["axes.unicode_minus"] = False


# ── API 호출 + 캐시 ───────────────────────────────
def validate_kobis_response(data: dict, target: date) -> None:
    """KOBIS 오류 응답을 조용히 빈 데이터처럼 처리하지 않도록 확인."""
    fault = data.get("faultInfo")
    if fault:
        message = fault.get("message", "알 수 없는 오류")
        code = fault.get("errorCode", "UNKNOWN")
        raise RuntimeError(f"KOBIS API 오류({target:%Y-%m-%d}, {code}): {message}")
    if "boxOfficeResult" not in data:
        raise RuntimeError(f"KOBIS API 응답 구조가 예상과 다릅니다: {target:%Y-%m-%d}")


def fetch_daily(api_key: str, target: date, cache_dir: Path, force: bool) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{target:%Y%m%d}.json"
    if cache.exists() and not force:
        data = json.loads(cache.read_text(encoding="utf-8"))
        validate_kobis_response(data, target)
        return data
    params = urlencode({"key": api_key, "targetDt": f"{target:%Y%m%d}", "itemPerPage": "10"})
    with urlopen(f"{BASE_URL}?{params}", timeout=30) as r:
        payload = r.read().decode("utf-8")
    data = json.loads(payload)
    validate_kobis_response(data, target)
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(REQUEST_SLEEP_SEC)
    return data


# ── 전체 데이터 수집 ──────────────────────────────
def collect_daily_rows(api_key: str, start: date, end: date,
                        cache_dir: Path, force: bool) -> pd.DataFrame:
    rows: list[dict] = []
    dates = daterange(start, end)
    total = len(dates)

    for idx, d in enumerate(dates, 1):
        if idx == 1 or idx % 100 == 0 or idx == total:
            print(f"  [{idx:>4}/{total}] {d} 수집 중...")
        data = fetch_daily(api_key, d, cache_dir, force)
        daily_list = data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])
        for item in daily_list:
            rows.append({
                "date":         pd.Timestamp(d),
                "year":         d.year,
                "quarter":      f"{d.year}Q{(d.month - 1) // 3 + 1}",
                "rank":         to_int(item.get("rank")),
                "movie_cd":     item.get("movieCd", ""),
                "movie_nm":     item.get("movieNm", ""),
                "screen_count": to_int(item.get("scrnCnt")),
                "show_count":   to_int(item.get("showCnt")),
                "audience_cnt": to_int(item.get("audiCnt")),
                "audience_acc": to_int(item.get("audiAcc")),
            })

    if not rows:
        raise RuntimeError("수집된 데이터 없음 — API 키와 네트워크를 확인하세요.")

    df = pd.DataFrame(rows)
    daily_total = df.groupby("date")["screen_count"].transform("sum")
    df["screen_share"] = (df["screen_count"] / daily_total * 100).where(daily_total > 0, 0.0)
    return df


# ── 영화별 최대 누적 관객 ─────────────────────────
def movie_max_aud(df: pd.DataFrame) -> dict[str, int]:
    return df.groupby("movie_nm")["audience_acc"].max().to_dict()


# ── 분기별 TOP10 집계 ─────────────────────────────
def build_quarterly_top10(df: pd.DataFrame) -> pd.DataFrame:
    max_aud = movie_max_aud(df)
    grp = (
        df.groupby(["quarter", "movie_nm"], as_index=False)
        .agg(
            movie_cd=("movie_cd", lambda values: " / ".join(sorted(set(values)))),
            screen_count=("screen_count", "sum"),
            show_count=("show_count", "sum"),
            audience_acc_max=("audience_acc", "max"),
            active_days=("date", "nunique"),
        )
    )
    totals = grp.groupby("quarter")["screen_count"].transform("sum")
    grp["quarter_screen_share"] = (grp["screen_count"] / totals * 100).where(totals > 0, 0)
    grp["quarter_rank"] = (
        grp.groupby("quarter")["quarter_screen_share"]
        .rank(method="first", ascending=False).astype(int)
    )
    grp["audience_tier"] = grp["movie_nm"].map(lambda nm: get_tier(max_aud.get(nm, 0)))
    return grp[grp["quarter_rank"] <= 10].sort_values(["quarter", "quarter_rank"])


# ── 단일 영화 40% / 50% 이상 이벤트 ─────────────
def detect_single_events(df: pd.DataFrame, max_aud: dict) -> pd.DataFrame:
    """날짜별 스크린 점유율 1위 영화 중 40% 이상인 행만 반환."""
    top1 = (
        df.sort_values(["date", "screen_share"], ascending=[True, False])
        .groupby("date", as_index=False)
        .first()
    )
    top1 = top1[top1["screen_share"] >= 40].copy()
    top1["threshold"] = top1["screen_share"].apply(lambda v: "50% 이상" if v >= 50 else "40% 이상")
    top1["final_aud"]  = top1["movie_nm"].map(lambda nm: max_aud.get(nm, 0))
    top1["tier"]       = top1["final_aud"].map(get_tier)
    top1["movie_label"]= top1.apply(lambda r: audience_label(r["movie_nm"], r["final_aud"]), axis=1)
    return top1[["date", "year", "movie_cd", "movie_nm", "movie_label",
                  "screen_share", "threshold", "screen_count", "final_aud", "tier"]].copy()


# ── 상위 1~3개 합산 60% / 70% 이상 이벤트 ────────
def detect_group_events(df: pd.DataFrame, max_aud: dict) -> pd.DataFrame:
    """
    날짜별 스크린 점유율 상위 1개, 2개, 3개 조합을 각각 계산해
    60% 이상인 조합을 모두 반환.

    예를 들어 1위 영화 혼자 60%를 넘더라도 2위까지, 3위까지 합산한
    집중도도 별도로 남긴다. 그래야 "상위 1~3개 영화" 기준을 나중에
    각각 비교할 수 있다.
    """
    rows: list[dict] = []
    for d, day_df in df.groupby("date"):
        sorted_day = day_df.sort_values("screen_share", ascending=False).head(3)
        for n in range(1, len(sorted_day) + 1):
            selected = [row for _, row in sorted_day.head(n).iterrows()]
            cumsum = sum(float(r["screen_share"]) for r in selected)
            if cumsum >= 60:
                threshold = "70% 이상" if cumsum >= 70 else "60% 이상"
                best_aud  = max(max_aud.get(r["movie_nm"], 0) for r in selected)
                rows.append({
                    "date":                 d,
                    "year":                 d.year,
                    "movie_count":          n,
                    "movies":               " / ".join(r["movie_nm"] for r in selected),
                    "movie_labels":         " / ".join(audience_label(r["movie_nm"], max_aud.get(r["movie_nm"], 0)) for r in selected),
                    "combined_screen_share": cumsum,
                    "threshold":            threshold,
                    "combined_screen_count": sum(r["screen_count"] for r in selected),
                    "best_aud":             best_aud,
                    "tier":                 get_tier(best_aud),
                })
    return pd.DataFrame(rows)


# ── 연속 구간 요약 ────────────────────────────────
def summarize_periods(events: pd.DataFrame, share_col: str, group_cols: list[str]) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    ev = events.sort_values(group_cols + ["date"]).copy()
    ev["prev_date"] = ev.groupby(group_cols)["date"].shift()
    ev["new_period"] = ev["prev_date"].isna() | ((ev["date"] - ev["prev_date"]).dt.days > 1)
    ev["period_id"]  = ev.groupby(group_cols)["new_period"].cumsum()
    summary = (
        ev.groupby(group_cols + ["period_id"], as_index=False)
        .agg(start_date=("date","min"), end_date=("date","max"),
             days=("date","nunique"), max_share=(share_col,"max"), avg_share=(share_col,"mean"))
        .drop(columns=["period_id"])
    )
    return summary.sort_values(["start_date", "max_share"], ascending=[True, False])


def attach_representative_group_movies(group_periods: pd.DataFrame, group_events: pd.DataFrame) -> pd.DataFrame:
    """합산 점유율 기간 요약표에 해당 기간의 대표 영화 조합을 붙인다."""
    if group_periods.empty or group_events.empty:
        return group_periods

    rows = []
    for _, period in group_periods.iterrows():
        mask = (
            (group_events["date"] >= period["start_date"])
            & (group_events["date"] <= period["end_date"])
            & (group_events["movie_count"] == period["movie_count"])
            & (group_events["threshold"] == period["threshold"])
            & (group_events["tier"] == period["tier"])
        )
        candidates = group_events[mask].sort_values("combined_screen_share", ascending=False)
        row = period.to_dict()
        if not candidates.empty:
            representative = candidates.iloc[0]
            row["representative_movies"] = representative["movies"]
            row["representative_movie_labels"] = representative["movie_labels"]
        else:
            row["representative_movies"] = ""
            row["representative_movie_labels"] = ""
        rows.append(row)

    return pd.DataFrame(rows)


def build_representative_group_events(group_events: pd.DataFrame) -> pd.DataFrame:
    """
    상위 1~3개 합산 이벤트 중 날짜별 대표 행을 고른다.

    daily CSV에는 1개/2개/3개 조합을 모두 남기되, 기간 요약과 차트는 하루가
    여러 번 집계되지 않도록 가장 높은 합산 점유율 행을 대표로 사용한다.
    """
    if group_events.empty:
        return group_events.copy()

    representative = (
        group_events.sort_values(["date", "combined_screen_share", "movie_count"])
        .drop_duplicates("date", keep="last")
        .sort_values("date")
        .copy()
    )
    representative["threshold"] = representative["combined_screen_share"].apply(
        lambda value: "70% 이상" if value >= 70 else "60% 이상"
    )
    return representative


# ── 범례 핸들 ─────────────────────────────────────
def tier_legend_handles(alpha_add: float = 0.2) -> list:
    items = [
        ("1000만+",  "1,000만+ 관객 (천만)"),
        ("900만+",   "900만+ 관객 (천만 근접)"),
        ("500만+",   "500만+ 관객"),
        ("500만미만", "500만 미만"),
    ]
    return [mpatches.Patch(color=TIER_COLORS[k], alpha=TIER_ALPHA + alpha_add, label=v)
            for k, v in items]


# ── 연속 구간 추출 (시각화용) ─────────────────────
def find_spans(bool_s: pd.Series, dates: pd.Series) -> list[tuple]:
    """True인 연속 구간 → (시작 Timestamp, 끝 Timestamp, 일수) 목록"""
    if len(bool_s) == 0:
        return []

    pairs = (
        pd.DataFrame({"date": pd.to_datetime(dates), "flag": bool_s.astype(bool)})
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )

    spans, in_span, s0, prev_d = [], False, None, None
    for _, row in pairs.iterrows():
        v = bool(row["flag"])
        d = row["date"]
        has_gap = prev_d is not None and (d - prev_d).days > 1

        if v and (not in_span or has_gap):
            if in_span and prev_d is not None:
                spans.append((s0, prev_d, (prev_d - s0).days + 1))
            in_span, s0 = True, d
        elif not v and in_span:
            end_d = prev_d if prev_d is not None else d
            spans.append((s0, end_d, (end_d - s0).days + 1))
            in_span = False
        prev_d = d

    if in_span:
        spans.append((s0, prev_d, (prev_d - s0).days + 1))
    return spans


# ══════════════════════════════════════════════════
# 시각화 1: 연도별 분기별 TOP10 누적 가로 막대
# ══════════════════════════════════════════════════
def save_yearly_quarter_charts(quarterly_top10: pd.DataFrame, chart_dir: Path) -> None:
    out = chart_dir / "quarterly_top10_by_year"
    out.mkdir(parents=True, exist_ok=True)

    # 전체 기간 글로벌 TOP10 색상 고정
    PALETTE = ["#E63946","#457B9D","#2A9D8F","#E9C46A","#F4A261",
               "#8338EC","#3A86FF","#FB5607","#FFBE0B","#8ECAE6"]
    global_rank = (
        quarterly_top10.groupby("movie_nm")["quarter_screen_share"].sum()
        .sort_values(ascending=False)
    )
    color_map = {nm: PALETTE[i % len(PALETTE)] for i, nm in enumerate(global_rank.index[:10])}

    years = sorted(quarterly_top10["quarter"].str[:4].astype(int).unique())
    for year in years:
        year_df = quarterly_top10[quarterly_top10["quarter"].str.startswith(str(year))]
        quarters = sorted(year_df["quarter"].unique())
        n_q = len(quarters)

        fig, axes = plt.subplots(1, n_q, figsize=(6 * n_q, 9), constrained_layout=True)
        if n_q == 1:
            axes = [axes]

        for ax, quarter in zip(axes, quarters):
            qdf = year_df[year_df["quarter"] == quarter].sort_values("quarter_screen_share")
            colors = [color_map.get(nm, "#AAAAAA") for nm in qdf["movie_nm"]]
            bars = ax.barh(qdf["movie_nm"], qdf["quarter_screen_share"],
                           color=colors, edgecolor="white", linewidth=0.5)
            for bar, val in zip(bars, qdf["quarter_screen_share"]):
                ax.text(bar.get_width() + 0.4, bar.get_y() + bar.get_height() / 2,
                        f"{val:.1f}%", va="center", fontsize=8)
            # 40% / 50% 기준선
            xlim = max(55, qdf["quarter_screen_share"].max() * 1.18)
            ax.axvspan(40, 50,  color="#F4A261", alpha=0.15, label="40% 이상")
            ax.axvspan(50, xlim, color="#E63946", alpha=0.10, label="50% 이상")
            ax.axvline(40, color="#F4A261", linewidth=1.2, linestyle="--")
            ax.axvline(50, color="#E63946", linewidth=1.2, linestyle="--")
            ax.set_xlim(0, xlim)
            ax.set_title(f"{quarter} TOP{len(qdf)}", fontsize=11, fontweight="bold")
            ax.set_xlabel("분기 스크린 점유율 (%)")
            ax.grid(axis="x", linestyle="--", alpha=0.4)
            ax.legend(fontsize=7, loc="lower right")

        fig.suptitle(f"{year}년 분기별 영화 스크린 점유율 TOP10", fontsize=14, fontweight="bold")
        path = out / f"{year}_quarterly_top10.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  저장: {path}")


# ══════════════════════════════════════════════════
# 시각화 2: 연도별 임계값 차트 (단일 40/50% + 합산 60/70%)
# ══════════════════════════════════════════════════
def save_yearly_threshold_charts(
        single_events: pd.DataFrame,
        group_events: pd.DataFrame,
        df_daily: pd.DataFrame,
        chart_dir: Path,
        max_aud: dict,
        end_date: date,
) -> None:
    out = chart_dir / "thresholds_by_year"
    out.mkdir(parents=True, exist_ok=True)

    years = sorted(
        set(single_events["year"].tolist() if not single_events.empty else []) |
        set(group_events["year"].tolist()  if not group_events.empty  else [])
    )

    for year in years:
        single = single_events[single_events["year"] == year] if not single_events.empty else pd.DataFrame()
        group  = group_events[group_events["year"] == year]   if not group_events.empty  else pd.DataFrame()

        yr_start = pd.Timestamp(date(year, 1, 1))
        yr_end   = min(pd.Timestamp(date(year, 12, 31)), pd.Timestamp(end_date))

        # 해당 연도 일별 1위 시계열 (배경 곡선용)
        yr_top1 = (
            df_daily[df_daily["year"] == year]
            .sort_values(["date", "screen_share"], ascending=[True, False])
            .groupby("date", as_index=False).first()
        )
        yr_top3 = df_daily[df_daily["year"] == year].copy()

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10),
                                        sharex=True, constrained_layout=True)
        fig.suptitle(f"{year}년 스크린 점유율 집중 구간", fontsize=15, fontweight="bold")

        # ── 상단: 단일 영화 40% / 50% ──────────────
        ax1.set_title("단일 영화 스크린 점유율 1위 추이", fontsize=12)
        ax1.set_ylabel("점유율 (%)")
        ax1.set_ylim(0, 105)
        ax1.grid(axis="y", linestyle="--", alpha=0.4)

        if not yr_top1.empty:
            ax1.fill_between(yr_top1["date"], yr_top1["screen_share"], alpha=0.12, color="#2A9D8F")
            ax1.plot(yr_top1["date"], yr_top1["screen_share"], color="#2A9D8F", linewidth=1.0)

        # 기준선
        ax1.axhline(40, color="#F4A261", linestyle="--", linewidth=1.4, label="40% 기준선")
        ax1.axhline(50, color="#E63946", linestyle="--", linewidth=1.4, label="50% 기준선")

        if not single.empty:
            # 40~50% 구간: 주황 음영
            above_40 = single[(single["screen_share"] >= 40) & (single["screen_share"] < 50)]
            spans_40 = find_spans(
                pd.Series([True] * len(above_40)),
                above_40["date"].reset_index(drop=True),
            )
            for s, e, _ in spans_40:
                ax1.axvspan(s, e, alpha=0.22, color="#F4A261", zorder=2)

            # 50% 이상 구간: 관객수 등급별 색상
            above_50 = single[single["threshold"] == "50% 이상"]
            spans_50 = find_spans(
                above_50["screen_share"].reset_index(drop=True) >= 50,
                above_50["date"].reset_index(drop=True),
            )
            for s, e, length in spans_50:
                sub  = single[(single["date"] >= s) & (single["date"] <= e)]
                best = sub["final_aud"].max()
                tier = get_tier(int(best))
                ax1.axvspan(s, e, alpha=TIER_ALPHA, color=TIER_COLORS[tier], zorder=3)
                mid = s + (e - s) / 2
                movie = sub["movie_nm"].mode().iloc[0] if not sub.empty else ""
                aud_txt = f"{best / 10000:.0f}만" if best > 0 else ""
                ax1.text(mid, 52, f"{movie}\n({aud_txt})",
                         ha="center", va="bottom", fontsize=6.5, color="#111111",
                         bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7),
                         zorder=5)

        leg1 = [
            mpatches.Patch(color="#F4A261", alpha=0.4, label="40% 이상 구간"),
        ] + tier_legend_handles() + [
            plt.Line2D([0], [0], color="#F4A261", linestyle="--", label="40% 기준선"),
            plt.Line2D([0], [0], color="#E63946", linestyle="--", label="50% 기준선"),
        ]
        ax1.legend(handles=leg1, loc="upper right", fontsize=7, ncol=2, framealpha=0.85)

        # ── 하단: 합산 60% / 70% ───────────────────
        ax2.set_title("상위 1~3개 영화 합산 스크린 점유율 추이", fontsize=12)
        ax2.set_ylabel("합산 점유율 (%)")
        ax2.set_ylim(0, 105)
        ax2.set_xlabel("날짜")
        ax2.grid(axis="y", linestyle="--", alpha=0.4)

        # 배경 합산 곡선 (해당 연도 날짜별 상위 3개 합산)
        bg_rows = []
        for d, day_df in yr_top3.groupby("date"):
            top3 = day_df.sort_values("screen_share", ascending=False).head(3)
            bg_rows.append({"date": d, "sum3": top3["screen_share"].sum()})
        bg = pd.DataFrame(bg_rows).sort_values("date")
        if not bg.empty:
            ax2.fill_between(bg["date"], bg["sum3"], alpha=0.10, color="#457B9D")
            ax2.plot(bg["date"], bg["sum3"], color="#457B9D", linewidth=1.0)

        ax2.axhline(60, color="#2A9D8F", linestyle="--", linewidth=1.4, label="60% 기준선")
        ax2.axhline(70, color="#264653", linestyle="--", linewidth=1.4, label="70% 기준선")

        if not group.empty:
            group_vis = build_representative_group_events(group)
            # 60~70% 구간: 청록 음영
            above_60 = group_vis[
                (group_vis["combined_screen_share"] >= 60)
                & (group_vis["combined_screen_share"] < 70)
            ]
            spans_60 = find_spans(
                pd.Series([True] * len(above_60)),
                above_60["date"].reset_index(drop=True),
            )
            for s, e, _ in spans_60:
                ax2.axvspan(s, e, alpha=0.22, color="#2A9D8F", zorder=2)

            # 70% 이상 구간: 관객수 등급별 색상
            above_70 = group_vis[group_vis["combined_screen_share"] >= 70]
            spans_70 = find_spans(
                pd.Series([True] * len(above_70)),
                above_70["date"].reset_index(drop=True),
            )
            for s, e, length in spans_70:
                sub  = group_vis[(group_vis["date"] >= s) & (group_vis["date"] <= e)]
                tier = get_tier(int(sub["best_aud"].max()))
                ax2.axvspan(s, e, alpha=TIER_ALPHA, color=TIER_COLORS[tier], zorder=3)
                mid = s + (e - s) / 2
                movies = sub["movies"].iloc[len(sub) // 2] if not sub.empty else ""
                aud    = sub["best_aud"].max()
                aud_txt = f"{aud / 10000:.0f}만" if aud > 0 else ""
                ax2.text(mid, 72, f"{movies.split('/')[0].strip()}\n({aud_txt})",
                         ha="center", va="bottom", fontsize=6.5, color="#111111",
                         bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7),
                         zorder=5)

        leg2 = [
            mpatches.Patch(color="#2A9D8F", alpha=0.4, label="60% 이상 구간"),
        ] + tier_legend_handles() + [
            plt.Line2D([0], [0], color="#2A9D8F", linestyle="--", label="60% 기준선"),
            plt.Line2D([0], [0], color="#264653", linestyle="--", label="70% 기준선"),
        ]
        ax2.legend(handles=leg2, loc="upper right", fontsize=7, ncol=2, framealpha=0.85)

        ax2.set_xlim(yr_start, yr_end)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax2.xaxis.set_major_locator(mdates.MonthLocator())

        path = out / f"{year}_screen_share_thresholds.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  저장: {path}")


# ── CSV 저장 ─────────────────────────────────────
def save_tables(df: pd.DataFrame, quarterly_top10: pd.DataFrame,
                single_events: pd.DataFrame, group_events: pd.DataFrame,
                single_periods: pd.DataFrame, group_periods: pd.DataFrame,
                table_dir: Path) -> None:
    table_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(table_dir / "daily_top10_screen_share.csv",         index=False, encoding="utf-8-sig")
    quarterly_top10.to_csv(table_dir / "quarterly_top10.csv",     index=False, encoding="utf-8-sig")
    single_events.to_csv(table_dir / "single_40_50_daily.csv",    index=False, encoding="utf-8-sig")
    group_events.to_csv(table_dir / "group_60_70_daily.csv",      index=False, encoding="utf-8-sig")
    single_periods.to_csv(table_dir / "single_40_50_periods.csv", index=False, encoding="utf-8-sig")
    group_periods.to_csv(table_dir / "group_60_70_periods.csv",   index=False, encoding="utf-8-sig")
    print(f"  CSV 6개 저장 완료 → {table_dir}")


# ── 콘솔 요약 ────────────────────────────────────
def print_summary(single_periods: pd.DataFrame, group_periods: pd.DataFrame,
                  total_days: int) -> None:
    print("\n" + "=" * 68)
    print("  스크린 점유율 분석 요약")
    print("=" * 68)

    def _show(df: pd.DataFrame, label: str, share_col: str) -> None:
        print(f"\n▶ {label}")
        if df.empty:
            print("  해당 구간 없음")
            return
        top = df.sort_values("days", ascending=False).head(15)
        for _, r in top.iterrows():
            print(f"  {r['start_date'].date()} ~ {r['end_date'].date()}  "
                  f"({r['days']:>3}일)  max={r[share_col]:.1f}%")
        total = df["days"].sum()
        print(f"  → 합계 {total}일 / {total_days}일 ({total / total_days * 100:.1f}%)")

    if not single_periods.empty:
        _show(single_periods[single_periods.get("threshold", pd.Series()) == "50% 이상"]
              if "threshold" in single_periods.columns else single_periods,
              "단일 영화 50% 이상", "max_share")
        _show(single_periods[single_periods.get("threshold", pd.Series()) == "40% 이상"]
              if "threshold" in single_periods.columns else pd.DataFrame(),
              "단일 영화 40% 이상 (50% 미만)", "max_share")

    if not group_periods.empty:
        _show(group_periods[group_periods.get("threshold", pd.Series()) == "70% 이상"]
              if "threshold" in group_periods.columns else group_periods,
              "상위 1~3개 합산 70% 이상", "max_share")
        _show(group_periods[group_periods.get("threshold", pd.Series()) == "60% 이상"]
              if "threshold" in group_periods.columns else pd.DataFrame(),
              "상위 1~3개 합산 60% 이상 (70% 미만)", "max_share")
    print("=" * 68)


# ── 메인 ─────────────────────────────────────────
def main() -> None:
    args       = parse_args()
    env_path   = Path(args.env_path)
    output_dir = Path(args.output_dir)
    cache_dir  = Path(args.cache_dir)
    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date   = datetime.strptime(args.end_date,   "%Y-%m-%d").date()

    print("=" * 60)
    print("  KOBIS 스크린 점유율 분석 시작")
    print(f"  기간: {start_date} ~ {end_date}")
    print(f"  총일수: {(end_date - start_date).days + 1}일 / 예상 소요: "
          f"약 {(end_date - start_date).days * REQUEST_SLEEP_SEC / 60:.1f}분 (캐시 없을 시)")
    print("=" * 60 + "\n")

    api_key = load_api_key(env_path)
    df      = collect_daily_rows(api_key, start_date, end_date, cache_dir, args.force_refresh)

    configure_korean_font()
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_dir = output_dir / "charts"
    table_dir = output_dir / "tables"

    max_aud        = movie_max_aud(df)
    quarterly_top10 = build_quarterly_top10(df)
    single_events  = detect_single_events(df, max_aud)
    group_events   = detect_group_events(df, max_aud)

    single_periods = summarize_periods(single_events, "screen_share",
                                        ["movie_nm", "threshold", "tier"])
    group_period_events = build_representative_group_events(group_events)
    group_periods  = summarize_periods(group_period_events, "combined_screen_share",
                                        ["movie_count", "threshold", "tier"])
    group_periods  = attach_representative_group_movies(group_periods, group_period_events)

    save_tables(df, quarterly_top10, single_events, group_events,
                single_periods, group_periods, table_dir)

    print("\n[차트 생성 중]")
    save_yearly_quarter_charts(quarterly_top10, chart_dir)
    save_yearly_threshold_charts(single_events, group_events, df, chart_dir, max_aud, end_date)

    total_days = (end_date - start_date).days + 1
    print_summary(single_periods, group_periods, total_days)
    print(f"\n완료 → {output_dir.resolve()}")


if __name__ == "__main__":
    main()
