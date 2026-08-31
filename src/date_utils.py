"""
date_utils.py
=============
「翌月分の予約投稿日時を計算する」「先月の期間を計算する」など、
月次バッチ処理に必要な日付計算をまとめたモジュール。
すべて日本時間（JST, UTC+9固定）で計算する。
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

_WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WEEKDAY_LABEL_JA = {"mon": "月", "tue": "火", "wed": "水", "thu": "木", "fri": "金", "sat": "土", "sun": "日"}


def now_jst() -> datetime:
    return datetime.now(JST)


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """year/month に delta ヶ月を加算した (year, month) を返す。"""
    zero_based = (month - 1) + delta
    new_year = year + zero_based // 12
    new_month = zero_based % 12 + 1
    return new_year, new_month


def next_month(base: date | None = None) -> tuple[int, int]:
    base = base or now_jst().date()
    return add_months(base.year, base.month, 1)


def previous_month(base: date | None = None) -> tuple[int, int]:
    """『先月』＝直近の完全に終了した月。バッチは月末近くに実行される想定。"""
    base = base or now_jst().date()
    return add_months(base.year, base.month, -1)


def month_label_ja(year: int, month: int) -> str:
    return f"{year}年{month}月"


def month_date_range(year: int, month: int) -> tuple[date, date]:
    """指定した年月の1日と末日を返す（アナリティクス集計期間用）。"""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def compute_publish_datetimes(year: int, month: int, weekdays: list[str], time_str: str) -> list[datetime]:
    """
    指定した年月のうち、指定した曜日すべてに対応する日付・時刻（JST）のリストを
    昇順で返す。例: 2026年9月、["mon","wed","fri"]、"10:00" なら
    9/2, 9/4, 9/7, 9/9, ... のようなdatetimeのリストになる。
    """
    target_indices = {_WEEKDAY_INDEX[w.lower()] for w in weekdays if w.lower() in _WEEKDAY_INDEX}
    if not target_indices:
        raise ValueError(f"publish_weekdays の値が不正です: {weekdays}")

    hour, minute = (int(x) for x in time_str.split(":"))
    last_day = calendar.monthrange(year, month)[1]

    results: list[datetime] = []
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        if d.weekday() in target_indices:
            results.append(datetime(year, month, day, hour, minute, tzinfo=JST))
    return results


def format_jst(dt: datetime, with_weekday: bool = True) -> str:
    weekday_ja = _WEEKDAY_LABEL_JA[list(_WEEKDAY_INDEX.keys())[dt.weekday()]] if with_weekday else ""
    suffix = f"({weekday_ja})" if with_weekday else ""
    return dt.strftime(f"%Y-%m-%d{suffix} %H:%M")


if __name__ == "__main__":
    y, m = next_month()
    print(f"来月: {month_label_ja(y, m)}")
    for dt in compute_publish_datetimes(y, m, ["mon", "wed", "fri"], "10:00"):
        print(" -", format_jst(dt))
