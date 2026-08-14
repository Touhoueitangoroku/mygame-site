#!/usr/bin/env python3
"""
mygame-site サイト内整合性チェックスクリプト

Unityとの連携は行わず、GachaCharacterData.csv・キャラクター画像・バナー画像を
手作業でコピーする運用を前提に、コピー漏れ・画像欠損・CSV不整合・リンク切れを
公開前に機械的に検出するためのツール。

- 外部ライブラリ不要（Python標準ライブラリのみ）
- 既存ファイルは一切変更・削除・移動しない（読み取り専用の検査のみ）
- 実行方法: mygame-site のルートで `python check_site.py`
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "GachaCharacterData.csv"
TIER_JSON_PATH = BASE_DIR / "data" / "tier.json"
EVENTS_JSON_PATH = BASE_DIR / "data" / "events.json"
CHAR_IMG_DIR = BASE_DIR / "img" / "characters"
CHAR_IMG2_DIR = BASE_DIR / "img" / "characterImages2"
BANNER_DIR = BASE_DIR / "img" / "banners"
EVENTS_DIR = BASE_DIR / "events"

REQUIRED_FIELDS = [
    "Name", "BaseHP", "BaseAttack", "Attribute",
    "Image", "Image2", "rare", "スキル文章", "リーダースキル文章",
]

# events.json の必須項目（id/type/title/periodText/banner/description）
EVENT_REQUIRED_FIELDS = ["id", "type", "title", "periodText", "banner", "description"]

# events.json の type に許可する値。今後種別を増やす場合はここに追加する。
EVENT_TYPE_CHOICES = {
    "event",
    "drop_event",
    "harvest_event",
    "gacha",
    "login_bonus",
    "campaign",
    "stage_release",
    "schedule",
}

HTML_FILES_FOR_BANNERS = ["index.html", "news.html"]  # events/*.html は別途 glob で追加
HTML_FILES_FOR_EVENT_LINKS = ["index.html", "news.html"]

SRC_ATTR_RE = re.compile(r'''(?:src|href)\s*=\s*["']([^"']+)["']''', re.IGNORECASE)
EVENT_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class Report:
    def __init__(self):
        self.lines = []
        self.error_count = 0
        self.warning_count = 0

    def passed(self, label):
        self.lines.append(f"[PASS] {label}")

    def error(self, label, items):
        self.error_count += len(items)
        self.lines.append(f"[ERROR] {label}: {len(items)}")
        for item in items:
            self.lines.extend(item)

    def warning(self, label, items):
        self.warning_count += len(items)
        self.lines.append(f"[WARNING] {label}: {len(items)}")
        for item in items:
            self.lines.extend(item)

    def blank(self):
        self.lines.append("")

    def render(self):
        return "\n".join(self.lines)


def load_csv_rows():
    """CSVを読み込み、(rows, error_message) を返す。BOM/CRLFに対応。CSV自体は書き換えない。"""
    if not CSV_PATH.exists():
        return None, f"CSVファイルが見つかりません: {CSV_PATH}"
    try:
        with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, "CSVにヘッダー行がありません"
            # ヘッダーの前後空白だけ許容して正規化（値そのものは変更しない）
            reader.fieldnames = [h.strip() if h else h for h in reader.fieldnames]
            rows = []
            for i, raw_row in enumerate(reader, start=2):  # 1行目はヘッダーなのでデータは2行目から
                row = {k: (v if v is not None else "") for k, v in raw_row.items()}
                row["__line__"] = i
                rows.append(row)
        return rows, None
    except Exception as e:
        return None, f"CSVの読み込みに失敗しました: {e}"


def row_label(row):
    name = (row.get("Name") or "").strip()
    if name:
        return name
    return f"(Name未設定・CSV {row['__line__']}行目)"


def check_csv_basic(report, rows):
    report.passed("CSV loaded (UTF-8 BOM / CRLF 対応)")

    # Name重複チェック
    names = [r.get("Name", "").strip() for r in rows if r.get("Name", "").strip()]
    dup_names = [name for name, cnt in Counter(names).items() if cnt > 1]
    if dup_names:
        items = [[f"  - {n}"] for n in sorted(dup_names)]
        report.error("Duplicate character names", items)
    else:
        report.passed("Character names are unique")

    # 必須項目の空欄チェック
    missing_items = []
    for row in rows:
        empty_fields = [f for f in REQUIRED_FIELDS if not (row.get(f) or "").strip()]
        if empty_fields:
            missing_items.append([
                f"  - {row_label(row)} (CSV {row['__line__']}行目)",
                f"    Missing fields: {', '.join(empty_fields)}",
            ])
    if missing_items:
        report.error("Rows with missing required fields", missing_items)
    else:
        report.passed("Required fields")


def check_character_images(report, rows):
    missing_list = []
    missing_detail = []
    referenced_image = set()
    referenced_image2 = set()

    for row in rows:
        image = (row.get("Image") or "").strip()
        image2 = (row.get("Image2") or "").strip()

        if image:
            referenced_image.add(image)
            path = CHAR_IMG_DIR / f"{image}.png"
            if not path.exists():
                missing_list.append([
                    f"  - {row_label(row)}",
                    f"    Image: {image}",
                    f"    Expected: {path.relative_to(BASE_DIR).as_posix()}",
                ])

        if image2:
            referenced_image2.add(image2)
            path = CHAR_IMG2_DIR / f"{image2}.png"
            if not path.exists():
                missing_detail.append([
                    f"  - {row_label(row)}",
                    f"    Image2: {image2}",
                    f"    Expected: {path.relative_to(BASE_DIR).as_posix()}",
                ])

    if missing_list:
        report.error("Missing list character images (img/characters/)", missing_list)
    else:
        report.passed("List character images (img/characters/)")

    if missing_detail:
        report.error("Missing detail character images (img/characterImages2/)", missing_detail)
    else:
        report.passed("Detail character images (img/characterImages2/)")

    # 孤立画像（CSVから参照されていないファイル）は WARNING のみ。削除・移動は一切しない。
    if CHAR_IMG_DIR.exists():
        actual_list = {p.stem for p in CHAR_IMG_DIR.glob("*.png")}
        orphan_list = sorted(actual_list - referenced_image)
        items = [[f"  - {name}.png"] for name in orphan_list]
        report.warning("Unused list character images (img/characters/)", items)

    if CHAR_IMG2_DIR.exists():
        actual_detail = {p.stem for p in CHAR_IMG2_DIR.glob("*.png")}
        orphan_detail = sorted(actual_detail - referenced_image2)
        items = [[f"  - {name}.png"] for name in orphan_detail]
        report.warning("Unused detail character images (img/characterImages2/)", items)


def check_tier(report, rows):
    if not TIER_JSON_PATH.exists():
        report.error("Tier data", [["  - tier.json が見つかりません"]])
        return

    import json
    try:
        with open(TIER_JSON_PATH, "r", encoding="utf-8-sig") as f:
            tier_data = json.load(f)
    except Exception as e:
        report.error("Tier data", [[f"  - tier.json の読み込みに失敗しました: {e}"]])
        return

    csv_names = {(r.get("Name") or "").strip() for r in rows if (r.get("Name") or "").strip()}

    unknown = []
    for tier_name, members in tier_data.items():
        if not isinstance(members, list):
            continue  # "S": "AUTO" のような非リスト値は対象外
        for name in members:
            if name not in csv_names:
                unknown.append([f"  - tier: {tier_name}, name: {name} (CSVに存在しません)"])

    if unknown:
        report.error("tier.json entries not found in CSV", unknown)
    else:
        report.passed("Tier data (tier.json ↔ CSV)")


def extract_src_paths(html_text):
    return SRC_ATTR_RE.findall(html_text)


def check_banners(report):
    html_files = []
    for name in HTML_FILES_FOR_BANNERS:
        p = BASE_DIR / name
        if p.exists():
            html_files.append(p)
    if EVENTS_DIR.exists():
        html_files.extend(sorted(EVENTS_DIR.glob("*.html")))

    referenced_banners = set()
    missing = []

    for html_path in html_files:
        try:
            text = html_path.read_text(encoding="utf-8-sig")
        except Exception as e:
            missing.append([f"  - {html_path.relative_to(BASE_DIR).as_posix()} を読み込めませんでした: {e}"])
            continue

        for src in extract_src_paths(text):
            if "banners/" not in src:
                continue
            filename = src.split("banners/", 1)[1]
            referenced_banners.add(filename)
            expected = BANNER_DIR / filename
            if not expected.exists():
                missing.append([
                    f"  - source: {html_path.relative_to(BASE_DIR).as_posix()}",
                    f"    referenced: {src}",
                    f"    expected: {expected.relative_to(BASE_DIR).as_posix()}",
                ])

    if missing:
        report.error("Missing banner files referenced in HTML", missing)
    else:
        report.passed("Banner references")

    if BANNER_DIR.exists():
        actual_banners = {p.name for p in BANNER_DIR.glob("*") if p.is_file()}
        orphan_banners = sorted(actual_banners - referenced_banners)
        items = [[f"  - {name}"] for name in orphan_banners]
        report.warning("Unused banner images (img/banners/)", items)


def check_event_links(report):
    # 静的HTML（index.html/news.html）に書かれた events/*.html へのリンクが
    # 実在するかどうかだけを検証する。
    #
    # 正式管理イベント（data/events.json に登録され detailPage を持つもの）の
    # リンク切れは check_events() 側で検証する。
    #
    # events/*.html に実在するがどこからも静的リンクされていないページを
    # 「孤立」として警告する判定はここでは行わない。news.html は
    # data/events.json を正本として JavaScript がリンクを動的生成する運用に
    # なっており、events.json に未登録の旧イベントページは過去URL維持のための
    # 意図的なアーカイブであって異常ではないため。
    broken = []

    for name in HTML_FILES_FOR_EVENT_LINKS:
        p = BASE_DIR / name
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8-sig")
        except Exception as e:
            broken.append([f"  - {name} を読み込めませんでした: {e}"])
            continue

        for href in extract_src_paths(text):
            m = re.match(r'^events/([^"\']+\.html)$', href)
            if not m:
                continue
            target_name = m.group(1)
            target_path = EVENTS_DIR / target_name
            if not target_path.exists():
                broken.append([
                    f"  - source: {name}",
                    f"    href: {href}",
                    f"    expected: events/{target_name}",
                ])

    if broken:
        report.error("Broken event page links", broken)
    else:
        report.passed("Event page links (index.html / news.html)")


def load_events():
    """events.json を読み込み、(events, error_message) を返す。JSON自体は書き換えない。"""
    if not EVENTS_JSON_PATH.exists():
        return None, f"events.json が見つかりません: {EVENTS_JSON_PATH}"

    import json
    try:
        with open(EVENTS_JSON_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        return None, f"events.json の読み込みに失敗しました: {e}"

    if not isinstance(data, list):
        return None, "events.json のトップレベルは配列（リスト）である必要があります"

    return data, None


def event_label(event, index):
    eid = event.get("id") if isinstance(event, dict) else None
    if isinstance(eid, str) and eid.strip():
        return eid.strip()
    return f"(id未設定・events.json {index}番目の要素)"


def is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def parse_event_date(value):
    """YYYY-MM-DD として実在する日付かどうかを検証する。不正なら None を返す。"""
    if not isinstance(value, str) or not EVENT_DATE_RE.match(value):
        return None
    from datetime import date
    y, m, d = (int(x) for x in value.split("-"))
    try:
        return date(y, m, d)
    except ValueError:
        return None  # 例: 2026-02-30 のような実在しない日付


def check_events(report):
    events, load_error = load_events()

    if load_error:
        report.error("Event data loaded (data/events.json)", [[f"  - {load_error}"]])
        return  # events.json が読めない場合でもこの関数を抜けるだけで他のチェックは継続する

    report.passed("Event data loaded (data/events.json)")

    labels = [event_label(e, i) for i, e in enumerate(events)]

    # ID重複チェック
    ids = [
        e.get("id").strip() for e in events
        if isinstance(e, dict) and isinstance(e.get("id"), str) and e.get("id").strip()
    ]
    dup_ids = sorted({eid for eid, cnt in Counter(ids).items() if cnt > 1})
    if dup_ids:
        report.error("Duplicate event IDs", [[f"  - {eid}"] for eid in dup_ids])
    else:
        report.passed("Event IDs are unique")

    # 必須項目チェック（id/type/title/periodText/banner/description）
    missing_items = []
    for label, event in zip(labels, events):
        if not isinstance(event, dict):
            missing_items.append([f"  - {label}: イベントがオブジェクト（辞書）ではありません"])
            continue
        for field in EVENT_REQUIRED_FIELDS:
            if is_blank(event.get(field)):
                missing_items.append([f"  - {label}: {field} is empty"])
    if missing_items:
        report.error("Event required fields", missing_items)
    else:
        report.passed("Event required fields")

    # type の許可値チェック
    bad_type_items = []
    for label, event in zip(labels, events):
        if not isinstance(event, dict):
            continue
        t = event.get("type")
        if is_blank(t):
            continue  # 必須項目チェックで報告済み
        if t not in EVENT_TYPE_CHOICES:
            bad_type_items.append([
                f"  - {label}",
                f"    type: {t!r}",
                f"    allowed: {', '.join(sorted(EVENT_TYPE_CHOICES))}",
            ])
    if bad_type_items:
        report.error("Event types", bad_type_items)
    else:
        report.passed("Event types")

    # start / end の日付チェック
    # ・両方なし → PASS（例: 開催時期未定のイベント）
    # ・片方だけ → ERROR（不完全な期間情報）
    # ・両方あり → YYYY-MM-DD として実在する日付か、start <= end か検証
    date_items = []
    for label, event in zip(labels, events):
        if not isinstance(event, dict):
            continue
        has_start = "start" in event and not is_blank(event.get("start"))
        has_end = "end" in event and not is_blank(event.get("end"))

        if not has_start and not has_end:
            continue

        if has_start != has_end:
            date_items.append([
                f"  - {label}",
                f"    start: {event.get('start')!r}",
                f"    end: {event.get('end')!r}",
                "    reason: start と end は両方揃っている必要があります",
            ])
            continue

        start_raw, end_raw = event.get("start"), event.get("end")
        start_date = parse_event_date(start_raw)
        end_date = parse_event_date(end_raw)

        if start_date is None or end_date is None:
            date_items.append([
                f"  - {label}",
                f"    start: {start_raw!r}",
                f"    end: {end_raw!r}",
                "    reason: YYYY-MM-DD形式の実在する日付ではありません",
            ])
        elif start_date > end_date:
            date_items.append([
                f"  - {label}",
                f"    start: {start_raw}",
                f"    end: {end_raw}",
                "    reason: start が end より後になっています",
            ])

    if date_items:
        report.error("Event dates", date_items)
    else:
        report.passed("Event dates")

    # banner の存在チェック（img/ 側のファイル移動・リネームは今回行わない）
    banner_items = []
    for label, event in zip(labels, events):
        if not isinstance(event, dict):
            continue
        banner = event.get("banner")
        if is_blank(banner) or not isinstance(banner, str):
            continue  # 必須項目チェックで報告済み
        if not (BASE_DIR / banner).exists():
            banner_items.append([
                f"  - {label}",
                f"    banner: {banner}",
            ])
    if banner_items:
        report.error("Event banners", banner_items)
    else:
        report.passed("Event banners")

    # detailPage の存在チェック（任意項目）＋ 同一detailPageの重複参照チェック
    detail_page_items = []
    detail_page_owners = {}
    for label, event in zip(labels, events):
        if not isinstance(event, dict):
            continue
        dp = event.get("detailPage")
        if dp is None or (isinstance(dp, str) and dp.strip() == ""):
            continue  # detailPage は任意項目
        if not isinstance(dp, str):
            detail_page_items.append([f"  - {label}: detailPage is not a string"])
            continue
        if not (BASE_DIR / dp).exists():
            detail_page_items.append([
                f"  - {label}",
                f"    detailPage: {dp}",
            ])
        detail_page_owners.setdefault(dp, []).append(label)

    for dp, owners in detail_page_owners.items():
        if len(owners) > 1:
            detail_page_items.append([
                f"  - {dp}",
                f"    referenced by: {', '.join(owners)}",
            ])

    if detail_page_items:
        report.error("Event detail pages", detail_page_items)
    else:
        report.passed("Event detail pages")

    # tags の形式チェック（任意項目。配列かつ全要素が文字列であること）
    tags_items = []
    for label, event in zip(labels, events):
        if not isinstance(event, dict):
            continue
        if "tags" not in event:
            continue  # tags は任意項目
        tags = event.get("tags")
        if not isinstance(tags, list):
            tags_items.append([f"  - {label}: tags is not an array ({tags!r})"])
            continue
        non_strings = [t for t in tags if not isinstance(t, str)]
        if non_strings:
            tags_items.append([f"  - {label}: tags contains non-string values ({non_strings!r})"])
    if tags_items:
        report.error("Event tags", tags_items)
    else:
        report.passed("Event tags")


def main():
    report = Report()
    report.lines.append("=== Genso Eitango Website Check ===")
    report.blank()

    rows, csv_error = load_csv_rows()
    if csv_error:
        report.error("CSV loaded", [[f"  - {csv_error}"]])
        print(report.render())
        print()
        print("-" * 33)
        print("RESULT: FAILED")
        print(f"Errors: {report.error_count}")
        print(f"Warnings: {report.warning_count}")
        sys.exit(1)

    check_csv_basic(report, rows)
    report.blank()
    check_character_images(report, rows)
    report.blank()
    check_tier(report, rows)
    report.blank()
    check_banners(report)
    report.blank()
    check_event_links(report)
    report.blank()
    check_events(report)

    print(report.render())
    print()
    print("-" * 33)
    result = "FAILED" if report.error_count > 0 else "PASSED"
    print(f"RESULT: {result}")
    print(f"Errors: {report.error_count}")
    print(f"Warnings: {report.warning_count}")

    sys.exit(1 if report.error_count > 0 else 0)


if __name__ == "__main__":
    main()
