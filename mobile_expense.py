import html
import json
import math
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import streamlit as st
import streamlit.components.v1 as components
import firebase_admin
from firebase_admin import credentials, firestore

# ══════════════════════════════════════════════════════════════
#  천도글라스 직원 폰 — 현장 지출 등록
#  (같은 장부를 쓰는 대표님 대시보드: cost_manager.py)
#  화면 원칙: 링크만 있으면 누구나 여는 화면이라, 장부에서 꺼내 보여 주는 것은 '현장 이름'뿐입니다.
# ══════════════════════════════════════════════════════════════

# ── 고정 값 ──────────────────────
CATEGORIES = ["식대/경비", "장비비", "자재비", "외주비", "인건비", "기타"]
CATEGORY_ICONS = {"식대/경비": "🍱", "장비비": "🚜", "자재비": "🧱", "외주비": "🤝", "인건비": "👷", "기타": "📦"}
PLACEHOLDERS = {"식대/경비": "예: 점심 식대 5명", "장비비": "예: 5톤 지게차", "자재비": "예: 실리콘 2박스",
                "외주비": "예: 실리콘 코킹 외주", "인건비": "예: 일당", "기타": "예: 주차비"}
FOOD_QUICK_ITEMS = [("점심", "점심 식대"), ("저녁", "저녁 식대"), ("간식·음료", "간식·음료")]
MEMORY_COOKIE = "cd_mobile_memory"      # 이 폰이 최근에 쓴 현장·내역을 기억하는 쿠키 이름
MAX_RECENT_SITES = 3                     # 최근 현장 단추 개수
MEMORY_SITES_KEEP = 5                    # 기억해 두는 현장 수
MEMORY_ITEMS_KEEP = 3                    # 항목마다 기억해 두는 내역 수
MEMORY_ITEM_CHARS = 30                   # 기억하는 내역 한 개의 최대 글자 수
MEMORY_MAX_CHARS = 3000                  # 쿠키 글 길이 상한(브라우저 한도 약 4KB)
CHIP_LABEL_CHARS = 12                    # 내역 단추에 보이는 최대 글자 수
DOUBLE_TAP_SECONDS = 10                  # 이 시간 안에 똑같은 값으로 또 누르면 '두 번 누름'으로 보고 한 번만 저장
KST = timezone(timedelta(hours=9))


# ── 순수 함수 (화면·장부와 떨어져 있어 따로 시험합니다) ──────────────────────
def kst_today() -> date:
    """한국 시간 오늘 날짜입니다(서버는 다른 나라 시간이라 아침엔 하루 전으로 잡힐 수 있음)."""
    return datetime.now(KST).date()


def to_amount(value):
    """장부 금액을 정수로 읽습니다. 48000 · '48,000' · '48,000원' · 48000.0 → 48000, 못 읽으면 None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if math.isfinite(value) else None     # NaN·무한대는 못 읽음
    digits = re.sub(r"[,\s원]", "", str(value or ""))
    if re.fullmatch(r"-?\d+", digits):
        return int(digits)
    if re.fullmatch(r"-?\d+\.0+", digits):                    # '48000.0'
        return int(digits.split(".")[0])
    return None


def normalize_date(value) -> str:
    """'2026-11-03' · '2026.11.03' · '2026/5/3' · '2026. 11. 03' · '2026년 11월 3일' → 'YYYY-MM-DD'. 못 읽으면 빈 글자."""
    m = re.match(r"\s*(\d{4})\D+(\d{1,2})\D+(\d{1,2})", str(value or ""))
    if not m:
        return ""
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return ""


def _as_list(value) -> list:
    """장부 배열을 안전하게 읽습니다(없거나 None·이상한 값이면 빈 목록)."""
    return value if isinstance(value, list) else []


def site_is_closed(data: dict) -> bool:
    """폰 목록에서 뺄 현장인지 봅니다 — 수금 끝(완료) 또는 대표님이 '시공 끝'을 누른 현장."""
    if str(data.get("status") or "").strip() == "완료":
        return True
    flag = data.get("work_done")
    return flag is True or str(flag).strip().lower() in ("true", "1")


def site_last_activity(data: dict) -> str:
    """그 현장에서 돈이 오간 마지막 날짜입니다(지출·수금 중 가장 최근, 대시보드와 같은 셈). 없으면 빈 글자."""
    dates = []
    for field in ("expenses", "collections"):
        for row in _as_list(data.get(field)):
            if not isinstance(row, dict):
                continue
            day = normalize_date(row.get("날짜"))
            if day:
                dates.append(day)
    return max(dates) if dates else ""


def site_index(projects: dict) -> dict:
    """현장마다 '닫힘 여부·마지막 날짜'만 남깁니다(장부 줄은 들고 다니지 않음). {이름: {"closed", "last"}}"""
    return {name: {"closed": site_is_closed(data or {}), "last": site_last_activity(data or {})}
            for name, data in projects.items()}


def ordered_site_names(index: dict, include_closed: bool) -> list:
    """열린 현장을 최근 활동순으로(같으면 이름순, 기록 없는 현장은 뒤), include_closed 면 닫힌 현장을 뒤에 붙입니다."""
    def sort_group(closed):
        names = [n for n, v in index.items() if v["closed"] == closed]
        names.sort()                                            # 같은 날짜끼리는 이름순
        names.sort(key=lambda n: index[n]["last"], reverse=True)  # 최근 날짜가 앞(빈 날짜는 맨 뒤)
        return names
    return sort_group(False) + (sort_group(True) if include_closed else [])


def parse_memory(raw) -> dict:
    """쿠키 글(URL 인코딩된 JSON)을 기억으로 읽습니다. 무엇이 와도 멈추지 않고, 모양이 틀리면 빈 기억."""
    empty = {"sites": [], "items": {}}
    try:
        data = json.loads(urllib.parse.unquote(str(raw or ""), errors="strict"))
    except (ValueError, UnicodeDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    sites = data.get("sites", [])
    items = data.get("items", {})
    if not isinstance(sites, list) or not isinstance(items, dict):
        return empty
    clean_items = {}
    for category, values in items.items():
        if category in CATEGORIES and isinstance(values, list):
            kept = [v for v in values if isinstance(v, str) and v.strip()]
            if kept:
                clean_items[category] = kept
    return {"sites": [s for s in sites if isinstance(s, str) and s], "items": clean_items}


def dump_memory(memory: dict) -> str:
    """기억을 쿠키에 넣을 글로 바꿉니다(따옴표·세미콜론 없는 URL 인코딩). 너무 길면 오래된 내역부터 줄입니다."""
    sites = list(memory.get("sites", []))
    items = {k: list(v) for k, v in memory.get("items", {}).items()}

    def encode():
        text = json.dumps({"sites": sites, "items": items}, ensure_ascii=False, separators=(",", ":"))
        return urllib.parse.quote(text, safe="")

    out = encode()
    while len(out) > MEMORY_MAX_CHARS and any(items.values()):
        longest = max(items, key=lambda k: len(items[k]))
        items[longest].pop()
        if not items[longest]:
            del items[longest]
        out = encode()
    while len(out) > MEMORY_MAX_CHARS and len(sites) > 1:
        sites.pop()
        out = encode()
    return out


def remember(memory: dict, site: str, category: str, item: str) -> dict:
    """방금 등록한 현장·내역을 기억 맨 앞에 넣은 새 기억을 돌려줍니다(원래 기억은 그대로)."""
    sites = [site] + [s for s in memory.get("sites", []) if s != site]
    items = {k: list(v) for k, v in memory.get("items", {}).items()}
    text = str(item or "").strip()[:MEMORY_ITEM_CHARS]
    if text:
        items[category] = ([text] + [v for v in items.get(category, []) if v != text])[:MEMORY_ITEMS_KEEP]
    return {"sites": sites[:MEMORY_SITES_KEEP], "items": items}


def recent_site_buttons(memory: dict, index: dict) -> tuple:
    """최근 현장 단추 목록(최대 3)과 '대신 규칙' 여부입니다.
    이 폰이 기억하는 현장 중 지금 열린 곳을 앞에, 남는 자리는 장부의 최근 활동 현장으로 채웁니다.
    이 폰 기억이 하나도 없으면 두 번째 값이 True(전부 장부 기준)."""
    mine = [s for s in memory.get("sites", []) if s in index and not index[s]["closed"]][:MAX_RECENT_SITES]
    others = [s for s in ordered_site_names(index, False) if s not in mine]
    return (mine + others)[:MAX_RECENT_SITES], not mine


def default_site(memory: dict, index: dict):
    """화면을 열 때 미리 골라 둘 현장 — 이 폰이 마지막에 쓴 열린 현장만. 기억이 없으면 None(직원이 직접 고름)."""
    for site in memory.get("sites", []):
        if site in index and not index[site]["closed"]:
            return site
    return None


def item_suggestions(category: str, memory: dict) -> list:
    """내역 칸 위 단추들 [(단추 글, 채울 내역)]. 식대는 기본 단추 + 이 폰이 최근 쓴 내역, 다른 항목은 최근 내역만."""
    chips = list(FOOD_QUICK_ITEMS) if category == "식대/경비" else []
    used = {fill for _, fill in chips}
    for text in memory.get("items", {}).get(category, []):
        if text not in used:
            label = text if len(text) <= CHIP_LABEL_CHARS else text[:CHIP_LABEL_CHARS] + "…"
            chips.append((label, text))
            used.add(text)
    return chips[:5]


def item_placeholder(category: str) -> str:
    """내역 칸의 예시 글입니다(항목마다 다름)."""
    return PLACEHOLDERS.get(category, "예: 점심 식대")


def amount_text(amount) -> str:
    """금액 확인 글자 — 48000 → '48,000원'. 0·음수·못 읽는 값은 빈 글자."""
    value = to_amount(amount)
    return f"{value:,}원" if value and value > 0 else ""


def is_duplicate(expenses, record: dict) -> bool:
    """같은 날·같은 금액 줄이 이미 있는지 봅니다(인건비는 작업자까지 같아야). 장부 모양이 달라도 멈추지 않습니다."""
    want_date = normalize_date(record.get("날짜"))
    want_amount = to_amount(record.get("금액"))
    labor = record.get("항목") == "인건비"
    want_worker = str(record.get("worker") or "").strip()
    for row in _as_list(expenses):
        if not isinstance(row, dict):
            continue
        if normalize_date(row.get("날짜")) != want_date or to_amount(row.get("금액")) != want_amount:
            continue
        if labor and str(row.get("worker") or "").strip() != want_worker:
            continue
        return True
    return False


def make_record(day: date, category: str, item: str, amount: int, worker: str) -> dict:
    """장부에 덧붙일 한 줄입니다(대시보드와 같은 모양). 인건비가 아니면 작업자는 비웁니다."""
    return {"날짜": day.isoformat(), "항목": category, "내역": str(item or "").strip(),
            "금액": int(amount), "worker": str(worker or "").strip() if category == "인건비" else ""}


def check_entry(site, category, item, amount, worker) -> str:
    """등록 전에 빠진 것을 찾습니다. 문제가 없으면 빈 글자, 있으면 직원에게 보여 줄 안내 글."""
    if not site:
        return "현장을 먼저 골라 주세요."
    if category not in CATEGORIES:
        return "지출 항목을 골라 주세요."
    value = to_amount(amount)
    if not value or value <= 0:
        return "결제 금액을 넣어 주세요."
    if not str(item or "").strip():
        return "상세 내역을 간단히라도 적어 주세요."
    if category == "인건비" and not str(worker or "").strip():
        return "작업자 이름을 적어 주세요."
    return ""


def entry_fingerprint(site: str, record: dict) -> str:
    """'그래도 등록할까요?'를 물었던 입력의 지문 — 입력이 하나라도 바뀌면 달라져 다시 검사합니다."""
    return json.dumps([site, record], ensure_ascii=False, sort_keys=True)


# ── 화면 설정 · 디자인 ──────────────────────
st.set_page_config(page_title="현장 지출", page_icon="🧾", layout="centered", initial_sidebar_state="collapsed")

# 피그마 후보 A '밝은 바탕 + 현장 머리 카드'의 배치·색 느낌을 천도 색으로 새로 만든 것(2026-11-24)
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{ --cd-navy:#1E3A5F; --cd-navy-ink:#15293F; --cd-sky:#2E86AB; --cd-sky-soft:#E8F3F8;
  --cd-gold:#F0A500; --cd-line:#DCE3EC; --cd-muted:#5F6B7A; --cd-bg:#F3F5F8; }

html, body, [class*="css"], [data-testid="stAppViewContainer"],
.stMarkdown, button, input, select, textarea, label{
  font-family:'Pretendard', -apple-system, system-ui, 'Malgun Gothic', sans-serif !important; }
[data-testid="stAppViewContainer"]{ background:var(--cd-bg); }
[data-testid="stHeader"]{ background:transparent; }
[data-testid="stMain"] .block-container{ padding-top:2.6rem; padding-bottom:3rem; max-width:560px; }

/* 맨 위 현장 머리 카드 — 지금 어느 현장에 넣는지 크게 */
.cd-head{ background:var(--cd-navy); color:#fff; border-radius:16px; padding:18px 20px 20px; margin:0 0 14px; }
.cd-head .k{ font-size:13px; color:#9CC7DB; letter-spacing:.02em; }
.cd-head .site{ font-size:25px; font-weight:800; line-height:1.25; margin-top:4px; word-break:keep-all; }
.cd-head .site.none{ color:#F3C969; font-size:21px; }
.cd-head .brand{ font-size:12px; color:#B7C4D4; margin-top:10px; }

/* 칸 묶음(흰 카드) — 그림자 없이 얇은 테두리만 */
[data-testid="stVerticalBlockBorderWrapper"]{ background:#fff; border:1px solid var(--cd-line) !important;
  border-radius:14px !important; }
.cd-sec{ font-size:15px; font-weight:800; color:var(--cd-navy); margin:0 0 2px; }
.cd-label{ font-size:15px; font-weight:700; color:var(--cd-navy); margin:4px 0 -6px; }
.cd-hint{ font-size:13px; color:var(--cd-muted); margin:0 0 6px; }

[data-testid="stWidgetLabel"] p{ color:var(--cd-navy) !important; font-weight:700; font-size:15px; }
div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-baseweb="base-input"]{
  background:#fff !important; border:1.5px solid var(--cd-line) !important; border-radius:10px !important; }
.stTextInput input, .stNumberInput input, .stDateInput input{ background:transparent !important;
  border:none !important; font-size:17px !important; }
div[data-baseweb="input"]:focus-within, div[data-baseweb="select"] > div:focus-within{
  border-color:var(--cd-sky) !important; }

/* 단추 공통 — 장갑 낀 손가락도 누르기 쉽게 큼직하게 */
.stButton>button{ border-radius:10px !important; font-weight:700 !important; font-size:16px !important;
  min-height:52px; padding:10px 12px !important; background:#fff !important; color:var(--cd-navy) !important;
  border:1.5px solid var(--cd-line) !important; box-shadow:none !important; }
.stButton>button:hover{ border-color:var(--cd-sky) !important; }
.stButton>button p{ font-weight:inherit !important; font-size:inherit !important; }   /* 단추 속 글자도 단추 굵기·크기를 따름 */
.stButton>button[kind="primary"], [data-testid="stBaseButton-primary"]{
  background:var(--cd-navy) !important; color:#fff !important; border-color:var(--cd-navy) !important; }

/* 내역 단추(작게) */
[class*="st-key-sug"] button{ min-height:44px !important; font-size:15px !important; background:var(--cd-sky-soft) !important;
  border-color:#BFDDEA !important; color:var(--cd-navy-ink) !important; }

/* 등록 — 골드 단색, 가장 크게 */
.st-key-save_btn button, .st-key-dup_force button{ min-height:58px !important; font-size:18px !important;
  font-weight:800 !important; background:var(--cd-gold) !important; color:var(--cd-navy-ink) !important;
  border:none !important; }
.st-key-dup_cancel button{ min-height:58px !important; }

/* 지출 항목 카드 6종 — 평평한 색(고르면 진한 바탕 + 흰 글씨) */
.st-key-cat0 button{ background:#FFF1EE !important; border-color:#F2A595 !important; }
.st-key-cat0 button[kind="primary"]{ background:#D9533B !important; color:#fff !important; border-color:#D9533B !important; }
.st-key-cat1 button{ background:#FFF6E0 !important; border-color:#EAC46E !important; }
.st-key-cat1 button[kind="primary"]{ background:#C98400 !important; color:#fff !important; border-color:#C98400 !important; }
.st-key-cat2 button{ background:#EAF4FB !important; border-color:#8CC6DF !important; }
.st-key-cat2 button[kind="primary"]{ background:#2E86AB !important; color:#fff !important; border-color:#2E86AB !important; }
.st-key-cat3 button{ background:#F1EEF8 !important; border-color:#B9AAD9 !important; }
.st-key-cat3 button[kind="primary"]{ background:#6E58A8 !important; color:#fff !important; border-color:#6E58A8 !important; }
.st-key-cat4 button{ background:#EAF6EF !important; border-color:#8FCCA9 !important; }
.st-key-cat4 button[kind="primary"]{ background:#2E8B57 !important; color:#fff !important; border-color:#2E8B57 !important; }
.st-key-cat5 button{ background:#EFF1F4 !important; border-color:#B3BBC6 !important; }
.st-key-cat5 button[kind="primary"]{ background:#5F6B7A !important; color:#fff !important; border-color:#5F6B7A !important; }

/* 여러 칸 줄 — 폰에서도 옆으로 나란히(세로로 쌓이지 않게), 폭은 넘치지 않게 */
[data-testid="stHorizontalBlock"]{ display:flex !important; flex-direction:row !important; flex-wrap:nowrap !important; gap:8px !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{ flex:1 1 0 !important; min-width:0 !important; width:auto !important; }

/* 금액 확인 글자 */
.cd-amount{ text-align:right; font-size:28px; font-weight:800; color:var(--cd-navy); margin:-4px 2px 4px; min-height:34px; }

/* 이 폰에서 넣은 것 */
.cd-row{ display:flex; justify-content:space-between; gap:10px; padding:9px 2px; border-bottom:1px solid #EEF1F5; font-size:14.5px; }
.cd-row:last-child{ border-bottom:none; }
.cd-row .l{ color:var(--cd-navy-ink); min-width:0; overflow-wrap:anywhere; }
.cd-row .l small{ color:var(--cd-muted); display:block; }
.cd-row .r{ font-weight:800; color:var(--cd-navy); white-space:nowrap; }
[data-testid="stAlert"]{ border-radius:10px; font-size:15px; }
</style>
""", unsafe_allow_html=True)

# ── Firebase 연결 ──────────────────────
# 스트림릿 비밀 금고(secrets)에서 열쇠를 꺼냅니다
if not firebase_admin._apps:
    try:
        key_dict = json.loads(st.secrets["firebase_key"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except KeyError:
        st.error("🔥 Firebase 키가 설정되지 않았습니다. Streamlit secrets에 'firebase_key'를 추가해주세요.")
        st.stop()
    except Exception as e:
        print(f"[폰 지출] Firebase 초기화 실패: {e!r}")    # 원인은 서버 기록에만(공개 화면엔 안 보임)
        st.error("🔥 장부 연결을 준비하지 못했어요. 사무실에 알려 주세요.")
        st.stop()

try:
    db = firestore.client()
except Exception as e:
    print(f"[폰 지출] Firestore 연결 실패: {e!r}")
    st.error("🔥 장부에 연결하지 못했어요. 와이파이/데이터를 확인하고 다시 열어 주세요.")
    st.stop()


# ── 장부 읽기 · 쓰기 ──────────────────────
@st.cache_data(ttl=10)
def load_site_index() -> dict:
    """현장 목록(닫힘 여부·마지막 날짜만)을 읽습니다. 10초 동안은 다시 읽지 않습니다."""
    docs = db.collection('projects').stream()
    return site_index({doc.id: (doc.to_dict() or {}) for doc in docs})


def add_expense(site: str, record: dict, force: bool) -> str:
    """장부 맨 끝에 한 줄 덧붙입니다(트랜잭션 — 최신 장부를 읽고 그 위에 씀, 남이 방금 넣은 줄을 지우지 않음).
    같은 날·같은 금액 줄이 있고 force 가 아니면 저장하지 않고 'duplicate', 저장했으면 'saved'.
    그 사이 현장이 지워졌거나 이름이 바뀌었으면 새로 만들지 않고 'missing'."""
    ref = db.collection('projects').document(site)

    @firestore.transactional
    def run(transaction):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            return 'missing'                # 빈 현장을 새로 만들지 않습니다(PC에서 지우거나 이름을 바꾼 현장)
        current = (snapshot.to_dict() or {}).get('expenses')
        if current is not None and not isinstance(current, list):
            # 장부 모양이 이상하면 덮어쓰지 않습니다(기존 기록을 잃지 않게)
            raise ValueError("이 현장의 장부 모양이 이상해서 저장하지 않았어요. 사무실에 알려 주세요.")
        expenses = current or []
        if not force and is_duplicate(expenses, record):
            return 'duplicate'
        transaction.update(ref, {'expenses': expenses + [record]})
        return 'saved'

    result = run(db.transaction())
    load_site_index.clear()       # 목록 순서(최근 활동)를 바로 새로
    return result


# ── 단추가 하는 일(콜백 — 화면을 다시 그리기 전에 실행돼 입력칸 값을 안전하게 바꿀 수 있음) ──────
ss = st.session_state


def pick_site(name: str):
    ss['site'] = name
    ss['dup_pending'] = None


def pick_site_from_list():
    if ss.get('site_pick'):
        pick_site(ss['site_pick'])
    ss['site_pick'] = None            # 찾기 칸은 비워 둠(다음에 단추로 고르면 헷갈리지 않게)


def pick_category(name: str):
    ss['category'] = name


def fill_item(text: str):
    ss['f_item'] = text


def cancel_duplicate():
    ss['dup_pending'] = None


def current_record():
    """지금 입력칸 값으로 만든 (현장, 장부 한 줄, 안내 글)."""
    site, category = ss.get('site'), ss.get('category')
    item, amount = ss.get('f_item', ''), ss.get('f_amount') or 0
    worker = ss.get('f_worker', '') if category == '인건비' else ''
    problem = check_entry(site, category, item, amount, worker)
    record = None if problem else make_record(ss.get('f_date') or kst_today(), category, item, amount, worker)
    return site, record, problem


def save_entry(force: bool = False):
    site, record, problem = current_record()
    if problem:
        ss['flash'] = ('warn', problem)
        return
    fingerprint = entry_fingerprint(site, record)
    saved_message = f"✔ {site} · {record['항목']} {amount_text(record['금액'])} 등록됨"
    last_fp, last_time = ss.get('last_saved', (None, 0))
    if not force and fingerprint == last_fp and time.time() - last_time < DOUBLE_TAP_SECONDS:
        # [등록]을 빠르게 두 번 눌렀을 때 — 두 번째는 저장하지 않고 '등록됨'을 그대로 보여 줍니다
        ss['f_item'], ss['f_amount'], ss['f_worker'] = '', 0, ''
        ss['flash'] = ('ok', saved_message + " (한 번만 저장했어요)")
        return
    if force and ss.get('dup_pending') != fingerprint:
        force = False                 # 확인을 물은 뒤 입력이 바뀌었으면 다시 검사
    try:
        result = add_expense(site, record, force)
    except Exception as e:
        print(f"[폰 지출] 등록 실패 ({site}): {e!r}")      # 원인은 서버 기록에만
        ss['flash'] = ('error', "등록하지 못했어요. 와이파이/데이터를 확인하고 다시 눌러 주세요.")
        return
    if result == 'missing':
        ss['site'], ss['dup_pending'] = None, None
        ss['flash'] = ('warn', "이 현장이 목록에서 없어졌어요(이름이 바뀌었거나 정리됨). 현장을 다시 골라 주세요.")
        return
    if result == 'duplicate':
        ss['dup_pending'] = fingerprint
        ss['flash'] = None
        return
    ss['dup_pending'] = None
    ss['last_saved'] = (fingerprint, time.time())
    ss['f_item'], ss['f_amount'], ss['f_worker'] = '', 0, ''
    ss['today_rows'].insert(0, dict(record, 현장=site))
    ss['memory'] = remember(ss['memory'], site, record['항목'], record['내역'])
    ss['cookie_pending'] = dump_memory(ss['memory'])
    ss['flash'] = ('ok', saved_message)


# ── 처음 열 때 준비 ──────────────────────
try:
    index = load_site_index()
    load_error = ""
except Exception as e:
    print(f"[폰 지출] 현장 목록 읽기 실패: {e!r}")
    index, load_error = {}, "현장 목록을 불러오지 못했어요. 와이파이/데이터를 확인하고 '다시 불러오기'를 눌러 주세요."

if 'memory' not in ss:
    try:
        raw_cookie = st.context.cookies.get(MEMORY_COOKIE)
    except Exception:
        raw_cookie = None                 # 쿠키를 못 읽는 환경이면 기억 없이 시작
    ss['memory'] = parse_memory(raw_cookie)
if not load_error:                        # 목록을 못 읽은 동안엔 고르기를 미뤄 둡니다(다시 불러오면 그때 정함)
    if 'site' not in ss:
        ss['site'] = default_site(ss['memory'], index)
    elif ss['site'] and ss['site'] not in index:
        ss['site'] = None                 # 그 사이 현장이 지워졌거나 이름이 바뀌었으면 다시 고르게
ss.setdefault('category', CATEGORIES[0])
ss.setdefault('f_date', kst_today())
# 화면을 밤새 켜 두었다가 다음 날 쓰면: 날짜 기본값을 오늘로, '오늘 넣은 것'은 비웁니다
if ss.setdefault('opened_day', kst_today()) != kst_today():
    ss['opened_day'] = ss['f_date'] = kst_today()
    ss['today_rows'] = []
ss.setdefault('f_item', '')
ss.setdefault('f_worker', '')
ss.setdefault('f_amount', 0)
ss.setdefault('dup_pending', None)
ss.setdefault('today_rows', [])
ss.setdefault('flash', None)

# ── 화면 ──────────────────────
site = ss.get('site')
if site:
    head_site = f'<div class="site">{html.escape(site)}</div>'
else:
    head_site = '<div class="site none">현장을 골라 주세요</div>'
st.markdown(f'<div class="cd-head"><div class="k">지금 넣는 현장</div>{head_site}'
            '<div class="brand">천도글라스 · 현장 지출 등록</div></div>', unsafe_allow_html=True)

if load_error:
    st.error(load_error)
    if st.button("다시 불러오기", key="reload_top", width='stretch'):
        st.cache_data.clear()
        st.rerun()
    st.stop()

# ① 현장
with st.container(border=True):
    buttons, is_fallback = recent_site_buttons(ss['memory'], index)
    st.markdown('<p class="cd-sec">현장</p>', unsafe_allow_html=True)
    if buttons:
        hint = "최근 기록 순 현장" if is_fallback else "이 폰에서 쓴 현장이 맨 앞"
        st.markdown(f'<p class="cd-hint">{hint}</p>', unsafe_allow_html=True)
    for i, name in enumerate(buttons):
        st.button(name, key=f"rs{i}", width='stretch', type="primary" if name == site else "secondary",
                  on_click=pick_site, args=(name,))
    show_closed = st.checkbox("끝난 현장도 보기", key="show_closed")
    names = ordered_site_names(index, show_closed)
    if not index:
        st.warning("지금 고를 수 있는 현장이 없어요. 사무실에 문의해 주세요.")
    elif not names:
        st.info("진행 중인 현장이 없어요. '끝난 현장도 보기'를 켜면 끝난 현장이 보여요.")
    st.selectbox("다른 현장 찾기", names, index=None, key="site_pick", placeholder="현장 이름을 눌러 찾기",
                 on_change=pick_site_from_list)

# ② 항목 · 내역 · 금액
with st.container(border=True):
    st.markdown('<p class="cd-sec">지출 항목</p>', unsafe_allow_html=True)
    for row_start in range(0, len(CATEGORIES), 2):
        cols = st.columns(2)
        for j, name in enumerate(CATEGORIES[row_start:row_start + 2]):
            cols[j].button(f"{CATEGORY_ICONS[name]}  {name}", key=f"cat{row_start + j}", width='stretch',
                           type="primary" if ss['category'] == name else "secondary",
                           on_click=pick_category, args=(name,))

    st.date_input("결제 날짜", key="f_date")

    # 이름표 → 내역 단추 → 입력칸 순서(단추가 '상세 내역'에 딸린 것으로 보이게)
    st.markdown('<p class="cd-label">상세 내역</p>', unsafe_allow_html=True)
    chips = item_suggestions(ss['category'], ss['memory'])
    for row_start in range(0, len(chips), 3):
        row = chips[row_start:row_start + 3]
        cols = st.columns(len(row))
        for j, (label, fill_text) in enumerate(row):
            cols[j].button(label, key=f"sug{row_start + j}", width='stretch', on_click=fill_item, args=(fill_text,))
    st.text_input("상세 내역", key="f_item", placeholder=item_placeholder(ss['category']),
                  label_visibility="collapsed")
    if ss['category'] == '인건비':
        st.text_input("작업자 이름", key="f_worker", placeholder="예: 김철수")
    st.number_input("결제 금액 (원)", key="f_amount", min_value=0, step=10000, format="%d")
    st.markdown(f'<div class="cd-amount">{amount_text(ss.get("f_amount"))}</div>', unsafe_allow_html=True)

    # 같은 날 같은 금액이 이미 있으면 한 번 더 묻습니다 — 입력이 바뀌었으면 묻기를 거둡니다
    pending = ss.get('dup_pending')
    if pending:
        site_now, record_now, _ = current_record()
        if record_now is None or entry_fingerprint(site_now, record_now) != pending:
            ss['dup_pending'] = pending = None
    if pending:
        st.warning("같은 날 같은 금액이 이미 있어요. 같은 영수증을 두 번 넣는 건 아닌지 확인해 주세요. 그래도 등록할까요?")
        c_yes, c_no = st.columns(2)
        c_yes.button("그래도 등록", key="dup_force", width='stretch', on_click=save_entry, args=(True,))
        c_no.button("취소", key="dup_cancel", width='stretch', on_click=cancel_duplicate)
    else:
        st.button("등록", key="save_btn", width='stretch', on_click=save_entry)

    flash = ss.get('flash')
    if flash:
        kind, message = flash
        {'ok': st.success, 'warn': st.warning, 'error': st.error}[kind](message)
        if kind == 'ok':
            st.toast(message)       # 다시 그리며 화면 위치가 바뀌어도 보이게 떠 있는 알림으로도
        ss['flash'] = None

# ③ 이 폰에서 오늘 넣은 것 (장부가 아니라 이 폰이 방금 등록한 줄만)
if ss['today_rows']:
    with st.container(border=True):
        st.markdown('<p class="cd-sec">이 폰에서 오늘 넣은 것</p>', unsafe_allow_html=True)
        lines = []
        for row in ss['today_rows'][:20]:
            lines.append(
                f'<div class="cd-row"><div class="l">{html.escape(row["내역"])}'
                f'<small>{html.escape(row["현장"])} · {html.escape(row["항목"])} · {row["날짜"][5:]}</small></div>'
                f'<div class="r">{amount_text(row["금액"])}</div></div>')
        st.markdown("".join(lines), unsafe_allow_html=True)

# ── 하단 도움말 ──────────────────────
with st.expander("❓ 입력이 안 될 때"):
    st.markdown("""
    - 현장이 목록에 없으면 **사무실에 연락**해 주세요 (끝난 현장은 '끝난 현장도 보기'를 켜면 보여요)
    - 등록이 안 되면 **와이파이/데이터**를 확인하고 다시 눌러 주세요
    - 같은 날 같은 금액을 또 넣으면 **한 번 더 물어봐요** (같은 영수증 두 번 넣기 방지)
    - 잘못 넣은 기록은 **사무실에 말씀**해 주세요 (폰에서는 고치거나 지울 수 없어요)
    """)
    if st.button("🔄 현장 목록 새로고침", key="reload_bottom"):
        st.cache_data.clear()
        st.rerun()

# 등록에 성공했으면 이 폰에 기억을 씁니다(쓰기가 막힌 폰이어도 화면 동작엔 영향 없음).
# 화면 맨 아래에 두는 이유: 위쪽에 끼우면 등록할 때마다 화면이 맨 위로 튑니다.
if ss.get('cookie_pending'):
    value = json.dumps(ss['cookie_pending'])
    components.html(
        "<script>try{window.parent.document.cookie=" + json.dumps(MEMORY_COOKIE + "=") + "+" + value +
        "+'; path=/; max-age=15552000; SameSite=Lax';}catch(e){}</script>", height=0)
    ss['cookie_pending'] = None
