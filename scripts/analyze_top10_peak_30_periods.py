from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

try:
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import pandas as pd
except ModuleNotFoundError as exc:
    raise SystemExit("필요한 패키지가 없습니다. `pip install pandas matplotlib` 실행 후 다시 실행해주세요.") from exc


LINUX_TABLE_DIR = Path("/home/yjm/data_journalism/task/kobis_screen_share_output/tables")
WINDOWS_TABLE_DIR = Path(
    r"\\wsl.localhost\Ubuntu\home\yjm\data_journalism\task\kobis_screen_share_output\tables"
)
DEFAULT_INPUT_FILE = "daily_top10_screen_share.csv"
DEFAULT_START_DATE = "2022-07-01"
DEFAULT_END_DATE = "2025-12-31"
DEFAULT_THRESHOLD = 30.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "2022년 7월부터 2025년 12월까지 스크린 점유율 최고점 TOP10 영화와 "
            "각 영화의 30% 초과 연속 기간을 분석합니다."
        )
    )
    parser.add_argument("--input-csv", default=None, help="daily_top10_screen_share.csv 경로")
    parser.add_argument("--output-dir", default=None, help="분석 결과 저장 폴더")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="분석 시작일")
    parser.add_argument("--end-date", default=DEFAULT_END_DATE, help="분석 종료일")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="스크린 점유율 기준값")
    parser.add_argument(
        "--inclusive",
        action="store_true",
        help="기준값 이상으로 계산합니다. 기본값은 '30% 초과'입니다.",
    )
    return parser.parse_args()


def resolve_input_csv(input_csv: str | None) -> Path:
    if input_csv:
        path = Path(input_csv)
        if not path.exists():
            raise FileNotFoundError(f"입력 CSV를 찾을 수 없습니다: {path}")
        return path

    candidates = [
        LINUX_TABLE_DIR / DEFAULT_INPUT_FILE,
        WINDOWS_TABLE_DIR / DEFAULT_INPUT_FILE,
        Path(DEFAULT_INPUT_FILE),
    ]
    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(
        "daily_top10_screen_share.csv를 찾을 수 없습니다. "
        "--input-csv로 파일 경로를 직접 지정해주세요."
    )


def resolve_output_dir(input_csv: Path, output_dir: str | None) -> Path:
    if output_dir:
        return Path(output_dir)
    if input_csv.parent.name == "tables":
        return input_csv.parent.parent / "top10_peak_30_period_analysis"
    return input_csv.parent / "top10_peak_30_period_analysis"


def configure_korean_font() -> None:
    from matplotlib import font_manager as fm

    available = {font.name for font in fm.fontManager.ttflist}
    for font in ["NanumGothic", "NanumBarunGothic", "Malgun Gothic", "AppleGothic", "Gulim", "Dotum"]:
        if font in available:
            plt.rcParams["font.family"] = font
            break
    else:
        print("[경고] 한글 폰트 미발견 — 텍스트가 깨질 수 있습니다.")
    plt.rcParams["axes.unicode_minus"] = False


def load_daily_data(input_csv: Path, start_date: str, end_date: str) -> pd.DataFrame:
    df = pd.read_csv(input_csv)
    required = {"date", "movie_nm", "screen_share", "screen_count"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {', '.join(sorted(missing))}")

    df["date"] = pd.to_datetime(df["date"])
    df["screen_share"] = pd.to_numeric(df["screen_share"], errors="coerce").fillna(0)
    df["screen_count"] = pd.to_numeric(df["screen_count"], errors="coerce").fillna(0).astype(int)

    if "audience_acc" in df.columns:
        df["audience_acc"] = pd.to_numeric(df["audience_acc"], errors="coerce").fillna(0).astype(int)
    else:
        df["audience_acc"] = 0

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    if end_ts < start_ts:
        raise ValueError(f"종료일({end_date})이 시작일({start_date})보다 빠릅니다.")

    filtered = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)].copy()
    if filtered.empty:
        raise RuntimeError(f"분석 기간에 해당하는 데이터가 없습니다: {start_date} ~ {end_date}")

    return filtered.sort_values(["date", "screen_share"], ascending=[True, False])


def find_top10_by_peak(df: pd.DataFrame) -> pd.DataFrame:
    peak_rows = (
        df.sort_values(["movie_nm", "screen_share", "date"], ascending=[True, False, True])
        .groupby("movie_nm", as_index=False)
        .first()
    )
    peak_rows = peak_rows.rename(
        columns={
            "date": "peak_date",
            "screen_share": "peak_screen_share",
            "screen_count": "peak_screen_count",
            "audience_acc": "audience_acc_at_peak",
        }
    )
    return (
        peak_rows[["movie_nm", "peak_date", "peak_screen_share", "peak_screen_count", "audience_acc_at_peak"]]
        .sort_values(["peak_screen_share", "peak_date"], ascending=[False, True])
        .head(10)
        .reset_index(drop=True)
    )


def threshold_mask(series: pd.Series, threshold: float, inclusive: bool) -> pd.Series:
    if inclusive:
        return series >= threshold
    return series > threshold


def find_over_threshold_periods(
    df: pd.DataFrame,
    top10_movies: list[str],
    threshold: float,
    inclusive: bool,
) -> pd.DataFrame:
    events = df[df["movie_nm"].isin(top10_movies)].copy()
    events = events[threshold_mask(events["screen_share"], threshold, inclusive)].copy()

    rows = []
    for movie_nm, movie_df in events.sort_values(["movie_nm", "date"]).groupby("movie_nm"):
        movie_df = movie_df.drop_duplicates("date").sort_values("date").copy()
        movie_df["prev_date"] = movie_df["date"].shift()
        movie_df["new_period"] = movie_df["prev_date"].isna() | (
            (movie_df["date"] - movie_df["prev_date"]).dt.days > 1
        )
        movie_df["period_id"] = movie_df["new_period"].cumsum()

        for _, period_df in movie_df.groupby("period_id"):
            peak = period_df.sort_values(["screen_share", "date"], ascending=[False, True]).iloc[0]
            rows.append(
                {
                    "movie_nm": movie_nm,
                    "start_date": period_df["date"].min(),
                    "end_date": period_df["date"].max(),
                    "days": period_df["date"].nunique(),
                    "max_share_in_period": period_df["screen_share"].max(),
                    "avg_share_in_period": period_df["screen_share"].mean(),
                    "peak_date_in_period": peak["date"],
                    "screen_count_at_period_peak": int(peak["screen_count"]),
                    "audience_acc_at_period_peak": int(peak["audience_acc"]),
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "movie_nm",
                "start_date",
                "end_date",
                "days",
                "max_share_in_period",
                "avg_share_in_period",
                "peak_date_in_period",
                "screen_count_at_period_peak",
                "audience_acc_at_period_peak",
            ]
        )

    return pd.DataFrame(rows).sort_values(["movie_nm", "start_date"]).reset_index(drop=True)


def add_period_summary(top10: pd.DataFrame, periods: pd.DataFrame) -> pd.DataFrame:
    if periods.empty:
        top10["over_threshold_total_days"] = 0
        top10["over_threshold_period_count"] = 0
        top10["longest_over_threshold_period_days"] = 0
        return top10

    period_summary = (
        periods.groupby("movie_nm", as_index=False)
        .agg(
            over_threshold_total_days=("days", "sum"),
            over_threshold_period_count=("days", "count"),
            longest_over_threshold_period_days=("days", "max"),
        )
    )
    merged = top10.merge(period_summary, on="movie_nm", how="left")
    for col in ["over_threshold_total_days", "over_threshold_period_count", "longest_over_threshold_period_days"]:
        merged[col] = merged[col].fillna(0).astype(int)
    return merged


def save_tables(top10: pd.DataFrame, periods: pd.DataFrame, output_dir: Path, threshold: float, inclusive: bool) -> None:
    table_dir = output_dir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    operator_tag = "gte" if inclusive else "gt"
    tag = f"{operator_tag}_{threshold:g}".replace(".", "_")

    top10.to_csv(table_dir / f"top10_peak_screen_share_{tag}.csv", index=False, encoding="utf-8-sig")
    periods.to_csv(table_dir / f"top10_movies_periods_over_{tag}.csv", index=False, encoding="utf-8-sig")


def plot_top10_peak(top10: pd.DataFrame, output_dir: Path, threshold: float) -> None:
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    plot_df = top10.sort_values("peak_screen_share")
    fig, ax = plt.subplots(figsize=(12, 7), constrained_layout=True)
    ax.barh(plot_df["movie_nm"], plot_df["peak_screen_share"], color="#457B9D")
    ax.axvline(threshold, color="#E76F51", linestyle="--", linewidth=1.3, label=f"{threshold:g}% 기준선")
    ax.set_title("2022년 7월~2025년 12월 스크린 점유율 최고점 TOP 10")
    ax.set_xlabel("최고 스크린 점유율(%)")
    ax.grid(axis="x", linestyle="--", alpha=0.35)
    ax.legend(loc="lower right")

    for idx, row in enumerate(plot_df.itertuples(index=False)):
        ax.text(
            row.peak_screen_share + 0.4,
            idx,
            f"{row.peak_screen_share:.1f}% ({row.peak_date.date()})",
            va="center",
            fontsize=8,
        )

    fig.savefig(chart_dir / "top10_peak_screen_share.png", dpi=180)
    plt.close(fig)


def plot_period_timeline(periods: pd.DataFrame, output_dir: Path, threshold: float) -> None:
    if periods.empty:
        return

    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    movies = periods["movie_nm"].drop_duplicates().tolist()
    y_pos = {movie_nm: idx for idx, movie_nm in enumerate(reversed(movies))}

    fig, ax = plt.subplots(figsize=(14, max(6, len(movies) * 0.55)), constrained_layout=True)
    colors = plt.cm.tab20.colors

    for idx, row in enumerate(periods.itertuples(index=False)):
        start = row.start_date
        end = row.end_date
        ax.barh(
            y_pos[row.movie_nm],
            (end - start).days + 1,
            left=start,
            height=0.48,
            color=colors[idx % len(colors)],
            alpha=0.88,
        )
        ax.text(
            start + (end - start) / 2,
            y_pos[row.movie_nm],
            f"{int(row.days)}일",
            ha="center",
            va="center",
            fontsize=7,
            color="white",
            fontweight="bold",
        )

    ax.set_yticks(list(y_pos.values()))
    ax.set_yticklabels(list(y_pos.keys()))
    ax.set_title(f"TOP10 영화별 스크린 점유율 {threshold:g}% 초과 연속 기간")
    ax.set_xlabel("날짜")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.grid(axis="x", linestyle="--", alpha=0.3)

    fig.savefig(chart_dir / "top10_movies_over_30_period_timeline.png", dpi=180)
    plt.close(fig)


def print_summary(top10: pd.DataFrame, periods: pd.DataFrame, threshold: float, inclusive: bool) -> None:
    operator = "이상" if inclusive else "초과"
    print("\n" + "=" * 72)
    print(f"2022-07-01 ~ 2025-12-31 스크린 점유율 최고점 TOP10 및 {threshold:g}% {operator} 기간")
    print("=" * 72)
    for _, row in top10.iterrows():
        print(
            f"{row['movie_nm']}: 최고 {row['peak_screen_share']:.1f}% "
            f"({row['peak_date'].date()}), {threshold:g}% {operator} "
            f"{int(row['over_threshold_total_days'])}일"
        )

    if periods.empty:
        print(f"\n{threshold:g}% {operator} 기간이 없습니다.")
        return

    print("\n기간 상세")
    for _, row in periods.iterrows():
        print(
            f"  {row['movie_nm']}: {row['start_date'].date()} ~ {row['end_date'].date()} "
            f"({int(row['days'])}일, 기간 내 최고 {row['max_share_in_period']:.1f}%)"
        )


def main() -> None:
    args = parse_args()
    input_csv = resolve_input_csv(args.input_csv)
    output_dir = resolve_output_dir(input_csv, args.output_dir)

    configure_korean_font()
    df = load_daily_data(input_csv, args.start_date, args.end_date)
    top10 = find_top10_by_peak(df)
    periods = find_over_threshold_periods(
        df,
        top10["movie_nm"].tolist(),
        args.threshold,
        args.inclusive,
    )
    top10 = add_period_summary(top10, periods)

    output_dir.mkdir(parents=True, exist_ok=True)
    save_tables(top10, periods, output_dir, args.threshold, args.inclusive)
    plot_top10_peak(top10, output_dir, args.threshold)
    plot_period_timeline(periods, output_dir, args.threshold)
    print_summary(top10, periods, args.threshold, args.inclusive)

    print(f"\n완료: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
