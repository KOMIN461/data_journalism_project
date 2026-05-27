#!/usr/bin/env python3
"""
Build screen concentration and efficiency indices for peak screen-share movies.

Inputs
------
1. top10 movie/period CSV from the previous 30% screen-share analysis.
2. daily_top10_screen_share.csv from the KOBIS screen-share pipeline.
3. KOBIS daily seat-occupancy .xls downloads in code_data/.

Outputs
-------
- screen_efficiency_daily_indices.csv
- screen_efficiency_movie_summary.csv
- screen_efficiency_dashboard_data.js

The formulas follow the attached dashboard's naming:
- SS: screen share
- SOI: seat share / audience share
- ScOI: screen share / audience share
- StEI: audience share / seat share
- ScEI: audience share / screen share
- MII: screen share * (1 - seat sales rate)
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_START_DATE = "2022-07-01"
DEFAULT_END_DATE = "2025-12-31"

SCEI_HIGH_THRESHOLD = 1.1
SCEI_LOW_THRESHOLD = 0.8
MII_CAUTION_THRESHOLD = 15
MII_HIGH_THRESHOLD = 20
SEAT_COVERAGE_WARNING_THRESHOLD = 80

KOREAN_DATE_PATTERN = re.compile(r"([0-9]{4})년\s*([0-9]{2})월\s*([0-9]{2})일")


@dataclass(frozen=True)
class InputPaths:
    code_data_dir: Path
    screen_daily_csv: Path
    top10_period_csv: Path | None
    output_dir: Path


def normalize_movie_name(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("：", ":")
    return text


def parse_number(value: object) -> float:
    if pd.isna(value):
        return math.nan
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "nan", "NaN", "None"}:
        return math.nan
    try:
        return float(text)
    except ValueError:
        return math.nan


def find_existing_path(candidates: Iterable[Path]) -> Path | None:
    for path in candidates:
        try:
            if path.exists():
                return path
        except OSError:
            continue
    return None


def default_paths() -> InputPaths:
    script_path = Path(__file__).resolve()
    repo_dir = script_path.parents[1]
    project_dir = script_path.parents[2]

    code_data_dir = find_existing_path(
        [
            Path("/home/yjm/data_journalism/task/code_data"),
            project_dir / "code_data",
            repo_dir / "code_data",
            Path.cwd() / "code_data",
        ]
    ) or project_dir / "code_data"

    screen_daily_csv = find_existing_path(
        [
            Path("/home/yjm/data_journalism/task/kobis_screen_share_output/tables/daily_top10_screen_share.csv"),
            Path("/home/yjm/data_journalism/research/docs/data/daily_top10_screen_share.csv"),
            repo_dir / "docs" / "data" / "daily_top10_screen_share.csv",
            project_dir / "docs" / "data" / "daily_top10_screen_share.csv",
            Path.cwd() / "daily_top10_screen_share.csv",
        ]
    ) or repo_dir / "docs" / "data" / "daily_top10_screen_share.csv"

    top10_period_csv = find_existing_path(
        [
            repo_dir / "docs" / "data" / "top10_movies_periods_over_gt_30.csv",
            project_dir / "docs" / "data" / "top10_movies_periods_over_gt_30.csv",
            Path.cwd() / "top10_movies_periods_over_gt_30.csv",
            Path("/home/yjm/data_journalism/task/kobis_screen_share_output/top10_peak_30_period_analysis/tables/top10_movies_periods_over_gt_30.csv"),
        ]
    )

    output_dir = repo_dir / "docs" / "data" / "screen_efficiency_indices"
    return InputPaths(code_data_dir, screen_daily_csv, top10_period_csv, output_dir)


def extract_dates_from_html(path: Path) -> list[pd.Timestamp]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    dates = []
    for year, month, day in KOREAN_DATE_PATTERN.findall(text):
        dates.append(pd.Timestamp(f"{year}-{month}-{day}"))
    # KOBIS HTML은 날짜(최신->과거)와 read_html 파싱 테이블(최신->과거)이
    # 동일한 방향이므로 reversed() 없이 zip하면 정확히 대응됩니다.
    return dates


def clean_seat_table(table: pd.DataFrame, date: pd.Timestamp, source_file: Path) -> pd.DataFrame:
    df = table.copy()
    df.columns = [str(col).strip() for col in df.columns]

    required = {"영화명", "좌석판매율", "좌석점유율", "좌석수", "관객수", "누적관객수"}
    if not required.issubset(set(df.columns)):
        return pd.DataFrame()

    df["date"] = date
    df["source_file"] = source_file.name
    df["movie_nm"] = df["영화명"].map(normalize_movie_name)
    df["open_date"] = pd.to_datetime(df.get("개봉일"), errors="coerce")
    df["seat_sales_rate_pct"] = df["좌석판매율"].map(parse_number)
    df["seat_share_pct_from_kobis"] = df["좌석점유율"].map(parse_number)
    df["seats_cnt"] = df["좌석수"].map(parse_number)
    df["audi_cnt"] = df["관객수"].map(parse_number)
    df["audi_acc"] = df["누적관객수"].map(parse_number)
    return df[
        [
            "date",
            "movie_nm",
            "open_date",
            "seat_sales_rate_pct",
            "seat_share_pct_from_kobis",
            "seats_cnt",
            "audi_cnt",
            "audi_acc",
            "source_file",
        ]
    ]


def load_kobis_seat_files(code_data_dir: Path) -> pd.DataFrame:
    if not code_data_dir.exists():
        raise FileNotFoundError(f"code_data folder not found: {code_data_dir}")

    rows: list[pd.DataFrame] = []
    files = sorted(code_data_dir.glob("*.xls"))
    if not files:
        raise FileNotFoundError(f"No .xls files found in: {code_data_dir}")

    for path in files:
        dates = extract_dates_from_html(path)
        tables = pd.read_html(path, encoding="utf-8", header=0)
        daily_tables = tables[1:] if len(tables) > 1 else []
        if len(dates) != len(daily_tables):
            print(f"[경고] 날짜 수와 표 수가 다릅니다: {path.name} dates={len(dates)} tables={len(daily_tables)}")

        for date, table in zip(dates, daily_tables):
            cleaned = clean_seat_table(table, date, path)
            if not cleaned.empty:
                rows.append(cleaned)

    if not rows:
        raise ValueError("No usable seat-occupancy tables were parsed.")

    combined = pd.concat(rows, ignore_index=True)
    combined = combined[combined["movie_nm"] != ""].copy()
    combined = combined.sort_values(["date", "movie_nm", "source_file"])
    combined = combined.drop_duplicates(["date", "movie_nm"], keep="last")

    totals = (
        combined.groupby("date", as_index=False)
        .agg(total_seats_cnt=("seats_cnt", "sum"), total_audi_cnt=("audi_cnt", "sum"))
    )
    combined = combined.merge(totals, on="date", how="left")
    combined["audience_share_pct"] = (
        combined["audi_cnt"] / combined["total_audi_cnt"].replace(0, float("nan")) * 100
    )
    combined["seat_share_pct"] = (
        combined["seats_cnt"] / combined["total_seats_cnt"].replace(0, float("nan")) * 100
    )
    # seat_share_pct_from_kobis is KOBIS's own seat share value from the "좌석점유율" column.
    # seat_share_pct is recalculated from the rows present in the downloaded XLS.
    combined["seat_share_recalc_vs_kobis_gap_p"] = (
        combined["seat_share_pct"] - combined["seat_share_pct_from_kobis"]
    )
    return combined


def load_screen_daily(screen_daily_csv: Path) -> pd.DataFrame:
    if not screen_daily_csv.exists():
        raise FileNotFoundError(f"screen daily CSV not found: {screen_daily_csv}")

    df = pd.read_csv(screen_daily_csv)
    required = {"date", "movie_nm", "screen_share", "screen_count", "show_count", "audience_cnt"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"screen daily CSV missing columns: {sorted(missing)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    nat_count = df["date"].isna().sum()
    if nat_count:
        print(f"[경고] screen daily CSV에서 날짜 파싱 실패 행 {nat_count}개가 제외됩니다.")
        df = df[df["date"].notna()].copy()
    df["movie_nm"] = df["movie_nm"].map(normalize_movie_name)
    df["SS_screen_share_pct"] = df["screen_share"].map(parse_number)
    max_screen_share = df["SS_screen_share_pct"].dropna().max()
    if pd.notna(max_screen_share) and max_screen_share <= 1.5:
        print(
            f"[경고] screen_share 최대값이 {max_screen_share:.4f}입니다. "
            "소수(0~1) 단위일 수 있으니 CSV 원본을 확인하세요."
        )
    df["scrn_cnt"] = df["screen_count"].map(parse_number)
    df["show_cnt"] = df["show_count"].map(parse_number)
    df["screen_audi_cnt"] = df["audience_cnt"].map(parse_number)
    keep = [
        "date",
        "movie_nm",
        "movie_cd",
        "rank",
        "scrn_cnt",
        "show_cnt",
        "screen_audi_cnt",
        "SS_screen_share_pct",
    ]
    keep = [col for col in keep if col in df.columns]
    return df[keep].copy()


def derive_top10_from_screen_daily(
    screen_daily: pd.DataFrame, start_date: str, end_date: str
) -> pd.DataFrame:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    scoped = screen_daily[(screen_daily["date"] >= start) & (screen_daily["date"] <= end)].copy()
    scoped = scoped[scoped["SS_screen_share_pct"].notna()]
    if scoped.empty:
        raise ValueError("No screen-share rows are available for deriving TOP10 movies.")
    idx = scoped.groupby("movie_nm")["SS_screen_share_pct"].idxmax()
    peak = scoped.loc[idx].sort_values("SS_screen_share_pct", ascending=False).head(10)
    return pd.DataFrame(
        {
            "movie_nm": peak["movie_nm"].values,
            "peak_date": peak["date"].dt.strftime("%Y-%m-%d").values,
            "peak_screen_share": peak["SS_screen_share_pct"].values,
            "period_start": "",
            "period_end": "",
            "period_days": "",
        }
    )


def load_top10_movies(
    top10_period_csv: Path | None,
    screen_daily: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if top10_period_csv and top10_period_csv.exists():
        df = pd.read_csv(top10_period_csv)
    else:
        print("[경고] TOP10 기간 CSV를 찾지 못해 daily_top10_screen_share.csv에서 TOP10을 재계산합니다.")
        df = derive_top10_from_screen_daily(screen_daily, start_date, end_date)

    movie_col = next(
        (col for col in ["movie_nm", "movie_name", "영화명"] if col in df.columns),
        None,
    )
    if movie_col is None:
        raise ValueError("TOP10 CSV must include movie_nm, movie_name, or 영화명.")

    df = df.copy()
    df["movie_nm"] = df[movie_col].map(normalize_movie_name)
    df = df[df["movie_nm"] != ""].drop_duplicates("movie_nm", keep="first")
    return df.head(10)


def infer_period_columns(top10_df: pd.DataFrame) -> tuple[str | None, str | None]:
    start_candidates = [
        "period_start",
        "period_start_date",
        "start_date",
        "start",
        "over_30_start",
        "over_30_start_date",
        "gt30_start",
        "gt30_start_date",
        "from_date",
        "시작일",
        "기간시작",
    ]
    end_candidates = [
        "period_end",
        "period_end_date",
        "end_date",
        "end",
        "over_30_end",
        "over_30_end_date",
        "gt30_end",
        "gt30_end_date",
        "to_date",
        "종료일",
        "기간종료",
    ]
    start_col = next((col for col in start_candidates if col in top10_df.columns), None)
    end_col = next((col for col in end_candidates if col in top10_df.columns), None)
    return start_col, end_col


def attach_period_flags(daily: pd.DataFrame, top10_df: pd.DataFrame) -> pd.DataFrame:
    start_col, end_col = infer_period_columns(top10_df)
    period_map = {}
    if start_col and end_col:
        for _, row in top10_df.iterrows():
            movie = row["movie_nm"]
            start = pd.to_datetime(row[start_col], errors="coerce")
            end = pd.to_datetime(row[end_col], errors="coerce")
            if not pd.isna(start) and not pd.isna(end):
                period_map[movie] = (start, end)
    if not period_map:
        if not start_col or not end_col:
            print("[경고] TOP10 CSV에서 기간 시작/종료 컬럼을 찾지 못했습니다. 전체 관측 기간으로 집계합니다.")
        else:
            start_all_empty = top10_df[start_col].replace("", pd.NA).isna().all()
            end_all_empty = top10_df[end_col].replace("", pd.NA).isna().all()
            if start_all_empty and end_all_empty:
                print("[정보] TOP10 기간 데이터가 없어 전체 관측 기간으로 집계합니다.")
            else:
                print("[경고] TOP10 CSV의 기간 날짜 파싱에 실패했습니다. 전체 관측 기간으로 집계합니다.")

    daily = daily.copy()
    daily["over_30_period_start"] = pd.NaT
    daily["over_30_period_end"] = pd.NaT
    daily["is_in_peak_over_30_period"] = False
    for movie, (start, end) in period_map.items():
        mask = (daily["movie_nm"] == movie) & (daily["date"] >= start) & (daily["date"] <= end)
        daily.loc[daily["movie_nm"] == movie, "over_30_period_start"] = start
        daily.loc[daily["movie_nm"] == movie, "over_30_period_end"] = end
        daily.loc[mask, "is_in_peak_over_30_period"] = True

    return daily


def build_daily_indices(
    top10_df: pd.DataFrame,
    screen_daily: pd.DataFrame,
    seat_daily: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    movies = set(top10_df["movie_nm"])
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    screen = screen_daily[
        (screen_daily["movie_nm"].isin(movies))
        & (screen_daily["date"] >= start)
        & (screen_daily["date"] <= end)
    ].copy()
    if screen.empty:
        raise ValueError(
            "스크린 점유율 데이터에서 TOP10 영화가 한 건도 매칭되지 않았습니다. "
            f"날짜 범위({start_date}~{end_date})와 영화명 정규화를 확인하세요."
        )

    seat_cols = [
        "date",
        "movie_nm",
        "open_date",
        "seat_sales_rate_pct",
        "seat_share_pct_from_kobis",
        "seat_share_pct",
        "seat_share_recalc_vs_kobis_gap_p",
        "audience_share_pct",
        "seats_cnt",
        "audi_cnt",
        "audi_acc",
        "total_seats_cnt",
        "total_audi_cnt",
    ]
    seat_filtered = seat_daily[seat_daily["movie_nm"].isin(movies)].copy()
    if seat_filtered.empty:
        raise ValueError(
            "좌석 데이터에서 TOP10 영화가 한 건도 매칭되지 않았습니다. "
            "영화명 정규화 또는 code_data 경로를 확인하세요."
        )
    matched_movies = set(seat_filtered["movie_nm"].dropna().unique())
    unmatched_movies = sorted(movies - matched_movies)
    if unmatched_movies:
        print("[주의] 좌석 데이터에서 매칭되지 않은 영화:", ", ".join(unmatched_movies))
    available_seat_cols = [col for col in seat_cols if col in seat_filtered.columns]
    merged = screen.merge(seat_filtered[available_seat_cols], on=["date", "movie_nm"], how="left")

    for source_col, new_col in [
        ("SS_screen_share_pct", "screen_share"),
        ("seat_share_pct", "seat_share"),
        ("audience_share_pct", "audience_share"),
        ("seat_sales_rate_pct", "seat_sales_rate"),
    ]:
        if source_col in merged.columns:
            merged[new_col] = merged[source_col] / 100
        else:
            merged[new_col] = float("nan")

    seat_s = merged["seat_share"].replace(0, float("nan"))
    audience_s = merged["audience_share"].replace(0, float("nan"))
    screen_s = merged["screen_share"].replace(0, float("nan"))

    merged["SOI_seat_overallocation"] = seat_s / audience_s
    merged["ScOI_screen_overallocation"] = screen_s / audience_s
    merged["StEI_seat_efficiency"] = audience_s / seat_s
    merged["ScEI_screen_efficiency"] = audience_s / screen_s
    merged["MII"] = merged["screen_share"] * (1 - merged["seat_sales_rate"])
    merged["MII_pct"] = merged["MII"] * 100
    merged["screen_minus_audience_share_p"] = (
        merged["SS_screen_share_pct"] - merged["audience_share_pct"]
    )
    merged["seat_minus_audience_share_p"] = merged["seat_share_pct"] - merged["audience_share_pct"]
    merged["has_seat_data"] = merged["seat_share_pct"].notna()

    merged = attach_period_flags(merged, top10_df)
    return merged.sort_values(["movie_nm", "date"]).reset_index(drop=True)


def first_valid(series: pd.Series) -> object:
    valid = series.dropna()
    return valid.iloc[0] if not valid.empty else math.nan


def col_mean(df: pd.DataFrame, col: str) -> float:
    return df[col].mean() if col in df.columns else math.nan


def col_max(df: pd.DataFrame, col: str) -> float:
    return df[col].max() if col in df.columns else math.nan


def summarize_movies(daily: pd.DataFrame, top10_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    movie_order = list(top10_df["movie_nm"]) if not top10_df.empty else list(daily["movie_nm"].drop_duplicates())
    for movie in movie_order:
        group = daily[daily["movie_nm"] == movie]
        if group.empty:
            continue
        group = group.sort_values("date")
        if group["SS_screen_share_pct"].notna().any():
            peak_idx = group["SS_screen_share_pct"].idxmax()
            peak = group.loc[peak_idx]
        else:
            peak = group.iloc[0]
        mii_idx = group["MII_pct"].idxmax() if group["MII_pct"].notna().any() else None
        mii_peak = group.loc[mii_idx] if mii_idx is not None else None

        period_rows = group[group["is_in_peak_over_30_period"]].copy()
        has_seat_data = group["has_seat_data"].fillna(False).astype(bool)
        analysis_rows = period_rows if not period_rows.empty else group
        analysis_scope = "over_30_period" if not period_rows.empty else "full_observed"

        rows.append(
            {
                "movie_nm": movie,
                "analysis_scope": analysis_scope,
                "observed_days": int(group["date"].nunique()),
                "seat_data_days": int(group.loc[has_seat_data, "date"].nunique()),
                "over_30_period_start": first_valid(group["over_30_period_start"]),
                "over_30_period_end": first_valid(group["over_30_period_end"]),
                "over_30_period_days_in_data": int(period_rows["date"].nunique()),
                "peak_screen_share_date": peak["date"],
                "peak_SS_screen_share_pct": peak["SS_screen_share_pct"],
                "peak_seat_share_pct": peak.get("seat_share_pct", math.nan),
                "peak_audience_share_pct": peak.get("audience_share_pct", math.nan),
                "peak_seat_sales_rate_pct": peak.get("seat_sales_rate_pct", math.nan),
                "peak_ScEI_screen_efficiency": peak.get("ScEI_screen_efficiency", math.nan),
                "peak_MII_pct": peak.get("MII_pct", math.nan),
                "max_MII_date": mii_peak["date"] if mii_peak is not None else pd.NaT,
                "max_MII_pct": mii_peak.get("MII_pct", math.nan) if mii_peak is not None else math.nan,
                "mean_SS_screen_share_pct": col_mean(analysis_rows, "SS_screen_share_pct"),
                "mean_seat_share_pct": col_mean(analysis_rows, "seat_share_pct"),
                "mean_audience_share_pct": col_mean(analysis_rows, "audience_share_pct"),
                "mean_seat_sales_rate_pct": col_mean(analysis_rows, "seat_sales_rate_pct"),
                "mean_SOI_seat_overallocation": col_mean(analysis_rows, "SOI_seat_overallocation"),
                "mean_ScOI_screen_overallocation": col_mean(analysis_rows, "ScOI_screen_overallocation"),
                "mean_StEI_seat_efficiency": col_mean(analysis_rows, "StEI_seat_efficiency"),
                "mean_ScEI_screen_efficiency": col_mean(analysis_rows, "ScEI_screen_efficiency"),
                "mean_MII_pct": col_mean(analysis_rows, "MII_pct"),
                "max_screen_minus_audience_share_p": col_max(
                    analysis_rows, "screen_minus_audience_share_p"
                ),
                "mean_screen_minus_audience_share_p": col_mean(
                    analysis_rows, "screen_minus_audience_share_p"
                ),
            }
        )

    summary = pd.DataFrame(rows)
    return summary.reset_index(drop=True)


def make_interpretation(summary: pd.DataFrame) -> pd.DataFrame:
    df = summary.copy()

    def label_efficiency(row: pd.Series) -> str:
        scei = row.get("mean_ScEI_screen_efficiency")
        mii = row.get("mean_MII_pct")
        if pd.isna(scei):
            return "좌석 데이터 부족"
        if scei >= SCEI_HIGH_THRESHOLD and (pd.isna(mii) or mii < MII_CAUTION_THRESHOLD):
            return "스크린 배정 대비 관객 효율 높음"
        if scei < SCEI_LOW_THRESHOLD and (not pd.isna(mii) and mii >= MII_CAUTION_THRESHOLD):
            return "스크린 집중 대비 효율 낮음"
        if not pd.isna(mii) and mii >= MII_HIGH_THRESHOLD:
            return "좌석 판매율을 함께 점검할 고비효율 구간"
        return "스크린 집중과 관객 효율이 중간 수준"

    df["interpretation"] = df.apply(label_efficiency, axis=1)
    return df


def dataframe_for_json(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    out = out.replace({pd.NaT: None})
    records = out.to_dict(orient="records")
    for record in records:
        for key, value in list(record.items()):
            if isinstance(value, (bool, np.bool_)):
                record[key] = bool(value)
            elif value is pd.NaT or str(value) == "NaT":
                record[key] = None
            elif isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                record[key] = None
    return records


def save_outputs(daily: pd.DataFrame, summary: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    daily_out = output_dir / "screen_efficiency_daily_indices.csv"
    summary_out = output_dir / "screen_efficiency_movie_summary.csv"
    js_out = output_dir / "screen_efficiency_dashboard_data.js"

    daily.to_csv(daily_out, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_out, index=False, encoding="utf-8-sig")

    payload = {
        "daily": dataframe_for_json(daily),
        "movieSummary": dataframe_for_json(summary),
    }
    js_text = "const screenEfficiencyDashboardData = "
    js_text += json.dumps(payload, ensure_ascii=False, indent=2)
    js_text += ";\n"
    js_out.write_text(js_text, encoding="utf-8")

    print(f"[완료] daily CSV: {daily_out}")
    print(f"[완료] summary CSV: {summary_out}")
    print(f"[완료] dashboard JS: {js_out}")


def warn_seat_coverage(daily: pd.DataFrame) -> None:
    if daily.empty or "has_seat_data" not in daily.columns:
        return

    coverage_source = daily.copy()
    coverage_source["has_seat_data_int"] = coverage_source["has_seat_data"].fillna(False).astype(int)
    seat_summary = coverage_source.groupby("movie_nm").agg(
        total_days=("date", "nunique"),
        seat_days=("has_seat_data_int", "sum"),
    )
    seat_summary["seat_coverage_pct"] = (
        seat_summary["seat_days"] / seat_summary["total_days"] * 100
    ).round(1)
    missing = seat_summary[seat_summary["seat_days"] == 0].index.tolist()
    partial = seat_summary[
        (seat_summary["seat_days"] > 0)
        & (seat_summary["seat_coverage_pct"] < SEAT_COVERAGE_WARNING_THRESHOLD)
    ]
    if missing:
        print("[경고] 좌석 데이터가 전혀 없는 영화:", ", ".join(missing))
    if not partial.empty:
        for movie, row in partial.iterrows():
            print(f"[주의] 좌석 데이터 부분 누락: {movie} ({row['seat_coverage_pct']}% 커버리지)")


def parse_args() -> argparse.Namespace:
    defaults = default_paths()
    parser = argparse.ArgumentParser(
        description="Build KOBIS screen concentration and efficiency indices from screen-share and seat-occupancy files."
    )
    parser.add_argument("--code-data-dir", type=Path, default=defaults.code_data_dir)
    parser.add_argument("--screen-daily-csv", type=Path, default=defaults.screen_daily_csv)
    parser.add_argument("--top10-period-csv", type=Path, default=defaults.top10_period_csv)
    parser.add_argument("--output-dir", type=Path, default=defaults.output_dir)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(f"[정보] code_data: {args.code_data_dir}")
    print(f"[정보] screen daily CSV: {args.screen_daily_csv}")
    top10_path_label = args.top10_period_csv or "(없음 - screen daily에서 재계산)"
    print(f"[정보] TOP10 period CSV: {top10_path_label}")

    screen_daily = load_screen_daily(args.screen_daily_csv)
    top10_df = load_top10_movies(
        args.top10_period_csv,
        screen_daily,
        args.start_date,
        args.end_date,
    )
    seat_daily = load_kobis_seat_files(args.code_data_dir)

    daily = build_daily_indices(
        top10_df=top10_df,
        screen_daily=screen_daily,
        seat_daily=seat_daily,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    summary = make_interpretation(summarize_movies(daily, top10_df))
    warn_seat_coverage(daily)
    save_outputs(daily, summary, args.output_dir)


if __name__ == "__main__":
    main()
