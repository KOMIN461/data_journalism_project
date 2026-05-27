from __future__ import annotations

import argparse
import colorsys
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KOBIS 스크린 점유율 결과 CSV에서 단일 영화 30% 이상 사례를 분석하고 시각화합니다."
    )
    parser.add_argument(
        "--input-csv",
        default=None,
        help="daily_top10_screen_share.csv 경로. 생략하면 기본 결과 폴더에서 자동 탐색합니다.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="분석 CSV와 시각화 PNG를 저장할 폴더. 생략하면 입력 CSV가 있는 결과 폴더 아래에 저장합니다.",
    )
    parser.add_argument("--threshold", type=float, default=30.0, help="단일 영화 스크린 점유율 기준값")
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
        return input_csv.parent.parent / "single_30_analysis"
    return input_csv.parent / "single_30_analysis"


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


def build_movie_color_map(movie_names: pd.Series | list[str]) -> dict[str, tuple[float, float, float]]:
    """영화별로 가능한 한 겹치지 않는 고유 색상을 만든다."""
    unique_movies = sorted(pd.Series(movie_names).dropna().unique())
    total = max(1, len(unique_movies))
    color_map: dict[str, tuple[float, float, float]] = {}

    for idx, movie_nm in enumerate(unique_movies):
        hue = (idx + 0.5) / total
        saturation = 0.64 + (idx % 3) * 0.09
        value = 0.72 + (idx % 2) * 0.16
        color_map[movie_nm] = colorsys.hsv_to_rgb(hue, min(saturation, 0.86), min(value, 0.9))

    return color_map


def load_daily_data(input_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(input_csv)
    required = {"date", "movie_nm", "screen_share", "screen_count"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {', '.join(sorted(missing))}")

    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    df["screen_share"] = pd.to_numeric(df["screen_share"], errors="coerce").fillna(0)
    df["screen_count"] = pd.to_numeric(df["screen_count"], errors="coerce").fillna(0).astype(int)

    if "audience_acc" in df.columns:
        df["audience_acc"] = pd.to_numeric(df["audience_acc"], errors="coerce").fillna(0).astype(int)
    else:
        df["audience_acc"] = 0

    return df.sort_values(["date", "screen_share"], ascending=[True, False])


def find_periods(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    rows = []
    for movie_nm, movie_df in events.sort_values(["movie_nm", "date"]).groupby("movie_nm"):
        for period_df in iter_continuous_movie_periods(movie_df):
            rows.append(
                {
                    "movie_nm": movie_nm,
                    "start_date": period_df["date"].min(),
                    "end_date": period_df["date"].max(),
                    "days": period_df["date"].nunique(),
                    "max_share": period_df["screen_share"].max(),
                    "avg_share": period_df["screen_share"].mean(),
                    "max_screen_count": period_df["screen_count"].max(),
                    "max_audience_acc": period_df["audience_acc"].max(),
                }
            )

    return pd.DataFrame(rows).sort_values(["days", "max_share"], ascending=[False, False])


def iter_continuous_movie_periods(movie_df: pd.DataFrame):
    movie_df = movie_df.drop_duplicates("date").sort_values("date").copy()
    movie_df["prev_date"] = movie_df["date"].shift()
    movie_df["new_period"] = movie_df["prev_date"].isna() | (
        (movie_df["date"] - movie_df["prev_date"]).dt.days > 1
    )
    movie_df["period_id"] = movie_df["new_period"].cumsum()
    for _, period_df in movie_df.groupby("period_id"):
        yield period_df


def find_movie_label_points(year_events: pd.DataFrame) -> pd.DataFrame:
    """연도별 차트에 표시할 영화명 라벨 위치를 연속 구간 단위로 고른다."""
    if year_events.empty:
        return pd.DataFrame()

    rows = []
    for movie_nm, movie_df in year_events.sort_values(["movie_nm", "date"]).groupby("movie_nm"):
        for period_df in iter_continuous_movie_periods(movie_df):
            label_row = period_df.sort_values("screen_share", ascending=False).iloc[0]
            rows.append(
                {
                    "date": label_row["date"],
                    "movie_nm": movie_nm,
                    "screen_share": label_row["screen_share"],
                    "days": period_df["date"].nunique(),
                }
            )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result[result["days"] >= 3]


def build_summaries(
    df: pd.DataFrame,
    threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    events = df[df["screen_share"] >= threshold].copy()
    daily_summary = (
        events.groupby("date", as_index=False)
        .agg(
            movie_count_over_threshold=("movie_nm", "nunique"),
            max_single_share=("screen_share", "max"),
            top_movie=("movie_nm", lambda values: values.iloc[0]),
        )
        .sort_values("date")
    )
    daily_summary["year"] = daily_summary["date"].dt.year

    movie_summary = (
        events.groupby("movie_nm", as_index=False)
        .agg(
            days_over_threshold=("date", "nunique"),
            max_share=("screen_share", "max"),
            avg_share=("screen_share", "mean"),
            max_screen_count=("screen_count", "max"),
            max_audience_acc=("audience_acc", "max"),
            first_date=("date", "min"),
            last_date=("date", "max"),
        )
        .sort_values(["days_over_threshold", "max_share"], ascending=[False, False])
    )

    year_summary = (
        daily_summary.groupby("year", as_index=False)
        .agg(
            days_with_any_movie_over_threshold=("date", "nunique"),
            max_single_share=("max_single_share", "max"),
        )
        .sort_values("year")
    )

    periods = find_periods(events)
    return events, daily_summary, movie_summary, year_summary, periods


def save_tables(
    events: pd.DataFrame,
    daily_summary: pd.DataFrame,
    movie_summary: pd.DataFrame,
    year_summary: pd.DataFrame,
    periods: pd.DataFrame,
    output_dir: Path,
    threshold: float,
) -> None:
    table_dir = output_dir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)

    tag = f"{threshold:g}".replace(".", "_")
    events.to_csv(table_dir / f"single_movie_over_{tag}_daily_events.csv", index=False, encoding="utf-8-sig")
    daily_summary.to_csv(table_dir / f"single_movie_over_{tag}_daily_summary.csv", index=False, encoding="utf-8-sig")
    movie_summary.to_csv(table_dir / f"single_movie_over_{tag}_movie_summary.csv", index=False, encoding="utf-8-sig")
    year_summary.to_csv(table_dir / f"single_movie_over_{tag}_year_summary.csv", index=False, encoding="utf-8-sig")
    periods.to_csv(table_dir / f"single_movie_over_{tag}_periods.csv", index=False, encoding="utf-8-sig")


def plot_yearly_days(year_summary: pd.DataFrame, output_dir: Path, threshold: float) -> None:
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 6), constrained_layout=True)
    ax.bar(year_summary["year"].astype(str), year_summary["days_with_any_movie_over_threshold"], color="#2A9D8F")
    ax.set_title(f"연도별 단일 영화 스크린 점유율 {threshold:g}% 이상 발생일수")
    ax.set_xlabel("연도")
    ax.set_ylabel("발생일수")
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    for idx, value in enumerate(year_summary["days_with_any_movie_over_threshold"]):
        ax.text(idx, value + 1, f"{int(value)}일", ha="center", va="bottom", fontsize=9)

    fig.savefig(chart_dir / f"yearly_days_single_movie_over_{threshold:g}.png", dpi=180)
    plt.close(fig)


def plot_top_movies(
    movie_summary: pd.DataFrame,
    output_dir: Path,
    threshold: float,
    movie_color_map: dict[str, tuple[float, float, float]],
    top_n: int = 20,
) -> None:
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    plot_df = movie_summary.head(top_n).sort_values("days_over_threshold")
    fig, ax = plt.subplots(figsize=(12, max(7, len(plot_df) * 0.5)), constrained_layout=True)
    colors = [movie_color_map.get(movie_nm, (0.28, 0.47, 0.62)) for movie_nm in plot_df["movie_nm"]]
    ax.barh(plot_df["movie_nm"], plot_df["days_over_threshold"], color=colors)
    ax.set_title(f"단일 영화 스크린 점유율 {threshold:g}% 이상 발생일수 TOP {min(top_n, len(plot_df))}")
    ax.set_xlabel("발생일수")
    ax.grid(axis="x", linestyle="--", alpha=0.35)

    for idx, value in enumerate(plot_df["days_over_threshold"]):
        ax.text(value + 0.5, idx, f"{int(value)}일", va="center", fontsize=8)

    fig.savefig(chart_dir / f"top_movies_days_single_movie_over_{threshold:g}.png", dpi=180)
    plt.close(fig)


def plot_yearly_timeline(
    events: pd.DataFrame,
    daily_summary: pd.DataFrame,
    output_dir: Path,
    threshold: float,
    movie_color_map: dict[str, tuple[float, float, float]],
) -> None:
    chart_dir = output_dir / "charts" / "yearly_timeline"
    chart_dir.mkdir(parents=True, exist_ok=True)

    for year in sorted(daily_summary["year"].unique()):
        year_df = daily_summary[daily_summary["year"] == year].copy()
        year_events = events[events["year"] == year].copy()
        if year_df.empty:
            continue

        year_start = pd.Timestamp(date(int(year), 1, 1))
        year_end = min(pd.Timestamp(date(int(year), 12, 31)), year_df["date"].max())

        fig, ax = plt.subplots(figsize=(15, 5), constrained_layout=True)
        point_colors = [movie_color_map.get(movie_nm, (0.28, 0.47, 0.62)) for movie_nm in year_df["top_movie"]]
        ax.scatter(
            year_df["date"],
            year_df["max_single_share"],
            c=point_colors,
            s=35,
            alpha=0.85,
        )
        ax.axhline(threshold, color="#E76F51", linestyle="--", linewidth=1.3, label=f"{threshold:g}% 기준선")
        ax.set_title(f"{year}년 단일 영화 스크린 점유율 {threshold:g}% 이상 날짜")
        ax.set_xlabel("날짜")
        ax.set_ylabel("해당일 최대 단일 영화 점유율(%)")
        ax.set_ylim(max(0, threshold - 5), max(55, year_df["max_single_share"].max() * 1.1))
        ax.set_xlim(year_start, year_end)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.grid(axis="y", linestyle="--", alpha=0.35)

        label_points = find_movie_label_points(year_events)
        if not label_points.empty:
            for idx, row in enumerate(label_points.sort_values("date").itertuples(index=False)):
                y_offset = 7 + (idx % 3) * 5
                label_color = movie_color_map.get(row.movie_nm, (0.15, 0.15, 0.15))
                ax.annotate(
                    row.movie_nm,
                    xy=(row.date, row.screen_share),
                    xytext=(0, y_offset),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    rotation=25,
                    color=label_color,
                    bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor=label_color, alpha=0.76),
                    arrowprops=dict(arrowstyle="-", color=label_color, linewidth=0.6, alpha=0.7),
                )

        legend_movies = year_df["top_movie"].drop_duplicates().head(16).tolist()
        baseline_handle = plt.Line2D(
            [0],
            [0],
            color="#E76F51",
            linestyle="--",
            linewidth=1.3,
            label=f"{threshold:g}% 기준선",
        )
        handles = [baseline_handle]
        if legend_movies:
            handles += [
                plt.Line2D(
                    [0],
                    [0],
                    marker="o",
                    linestyle="",
                    color=movie_color_map.get(movie_nm, (0.28, 0.47, 0.62)),
                    label=movie_nm,
                    markersize=5,
                )
                for movie_nm in legend_movies
            ]
        ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.86, ncol=2)

        fig.savefig(chart_dir / f"{year}_single_movie_over_{threshold:g}_timeline.png", dpi=180)
        plt.close(fig)


def print_summary(
    events: pd.DataFrame,
    daily_summary: pd.DataFrame,
    movie_summary: pd.DataFrame,
    periods: pd.DataFrame,
    threshold: float,
) -> None:
    print("\n" + "=" * 70)
    print(f"단일 영화 스크린 점유율 {threshold:g}% 이상 분석")
    print("=" * 70)
    print(f"일별 이벤트 행 수: {len(events):,}건")
    print(f"해당 날짜 수: {daily_summary['date'].nunique():,}일")
    print(f"해당 영화 수: {movie_summary['movie_nm'].nunique():,}편")

    if not movie_summary.empty:
        print("\n발생일수 TOP 10 영화")
        for _, row in movie_summary.head(10).iterrows():
            print(
                f"  {row['movie_nm']}: {int(row['days_over_threshold']):,}일 "
                f"(최대 {row['max_share']:.1f}%)"
            )

    if not periods.empty:
        print("\n가장 긴 연속 구간 TOP 10")
        for _, row in periods.head(10).iterrows():
            print(
                f"  {row['movie_nm']}: {row['start_date'].date()} ~ {row['end_date'].date()} "
                f"({int(row['days']):,}일, 최대 {row['max_share']:.1f}%)"
            )


def main() -> None:
    args = parse_args()
    input_csv = resolve_input_csv(args.input_csv)
    output_dir = resolve_output_dir(input_csv, args.output_dir)
    threshold = args.threshold

    configure_korean_font()
    df = load_daily_data(input_csv)
    events, daily_summary, movie_summary, year_summary, periods = build_summaries(df, threshold)
    movie_color_map = build_movie_color_map(movie_summary["movie_nm"])

    output_dir.mkdir(parents=True, exist_ok=True)
    save_tables(events, daily_summary, movie_summary, year_summary, periods, output_dir, threshold)
    plot_yearly_days(year_summary, output_dir, threshold)
    plot_top_movies(movie_summary, output_dir, threshold, movie_color_map)
    plot_yearly_timeline(events, daily_summary, output_dir, threshold, movie_color_map)
    print_summary(events, daily_summary, movie_summary, periods, threshold)

    print(f"\n완료: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
