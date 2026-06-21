import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json

# ── 모바일 최적화 설정 ──────────────────────
st.set_page_config(page_title="현장 지출", page_icon="🧾", layout="centered", initial_sidebar_state="collapsed")

# ── 천도글라스 브랜드 디자인 (모바일 · 화면 모양만, 기능 무관) ──────────────────────
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
:root{ --cd-navy:#1E3A5F; --cd-navy2:#356096; --cd-sky:#2E86AB; --cd-sky2:#4FB3D9;
  --cd-gold:#F0A500; --cd-gold2:#FFC847; --cd-line:#C7D2E0; --cd-muted:#6B7787; }

html, body, [class*="css"], [data-testid="stAppViewContainer"],
.stMarkdown, button, input, select, textarea, label{
  font-family:'Pretendard', -apple-system, system-ui, 'Malgun Gothic', sans-serif !important; }

[data-testid="stAppViewContainer"]{
  background:radial-gradient(900px 500px at 50% -10%, rgba(79,179,217,0.16), transparent 60%), #EEF2F7; }
[data-testid="stHeader"]{ background:transparent; }
[data-testid="stMain"] .block-container{ padding-top:1.2rem; max-width:560px; }

h1,h2,h3,h4{ color:var(--cd-navy) !important; font-weight:800 !important; letter-spacing:-0.01em; }

/* 상단 브랜드 헤더 */
.cd-mhero{ position:relative; overflow:hidden; border-radius:18px; padding:20px 22px; margin:2px 0 16px;
  background:linear-gradient(120deg,#1E3A5F 0%,#295082 55%,#2E86AB 130%); color:#fff;
  box-shadow:0 8px 22px rgba(30,58,95,0.20); }
.cd-mhero:after{ content:""; position:absolute; right:-30px; top:-40px; width:130px; height:130px;
  border-radius:50%; background:radial-gradient(circle, rgba(240,165,0,0.30), transparent 70%); }
.cd-mhero .t{ font-size:21px; font-weight:800; display:flex; align-items:center; gap:9px; position:relative; }
.cd-mhero .s{ font-size:13px; color:rgba(255,255,255,0.82); margin-top:5px; position:relative; }

/* 입력 라벨/위젯 — 큼직하게, 또렷한 테두리 (모바일 가독성) */
[data-testid="stWidgetLabel"] p{ color:var(--cd-navy) !important; font-weight:700; font-size:15px; }
div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-baseweb="base-input"]{
  background:#fff !important; border:1.5px solid var(--cd-line) !important; border-radius:12px !important;
  box-shadow:0 1px 2px rgba(30,58,95,0.05) !important; }
.stTextInput input, .stNumberInput input, .stDateInput input{
  background:transparent !important; border:none !important; font-size:16px !important; }
div[data-baseweb="input"]:focus-within, div[data-baseweb="select"] > div:focus-within{
  border-color:var(--cd-sky) !important; box-shadow:0 0 0 3px rgba(46,134,171,0.14) !important; }

/* 버튼 공통 */
.stButton>button, [data-testid="stFormSubmitButton"]>button{
  border-radius:12px !important; font-weight:700 !important;
  padding:14px 12px !important; font-size:15.5px !important; min-height:56px;
  transition:filter .15s, transform .05s, border-color .15s; }
/* 기본(미선택 항목 카드·새로고침) = 흰 카드 + 테두리 */
.stButton>button, .stButton>button:hover, .stButton>button:focus,
.stButton>button:focus-visible, .stButton>button:active{
  background:#fff !important; color:var(--cd-navy) !important;
  border:1.5px solid var(--cd-line) !important; box-shadow:0 1px 3px rgba(30,58,95,0.06) !important; outline:none !important; }
.stButton>button:hover{ border-color:var(--cd-sky) !important; background:#F6FAFD !important; }
/* 선택된 항목(primary) = 스카이→네이비 그라데이션 강조 */
.stButton>button[kind="primary"], .stButton>button[kind="primary"]:hover,
.stButton>button[kind="primary"]:focus, .stButton>button[kind="primary"]:active{
  background:linear-gradient(135deg,var(--cd-sky),var(--cd-navy)) !important; color:#fff !important;
  border:1.5px solid transparent !important; box-shadow:0 5px 14px rgba(46,134,171,0.32) !important; }
/* 등록(폼 제출) = 골드 그라데이션, 큼직하게 */
[data-testid="stFormSubmitButton"]>button{
  background:linear-gradient(135deg,var(--cd-gold2),var(--cd-gold)) !important; color:var(--cd-navy) !important;
  border:none !important; padding:15px 16px !important; font-size:17px !important; font-weight:800 !important;
  box-shadow:0 6px 16px rgba(240,165,0,0.30) !important; }
.stButton>button:active, [data-testid="stFormSubmitButton"]>button:active{ transform:translateY(1px); }

/* ── 지출 항목 카드별 색 (key=cat0~cat5 → .st-key-catN) ── */
/* 미선택: 연한 톤 배경 + 색 테두리 / 선택(primary): 진한 그라데이션 + 흰 글씨 */
.st-key-cat0 button{ background:#FFF1EE !important; border-color:#F8856F !important; }
.st-key-cat0 button[kind="primary"]{ background:linear-gradient(135deg,#FB8A7A,#EF5337) !important; color:#fff !important; border-color:transparent !important; box-shadow:0 5px 14px rgba(239,83,55,.30) !important; }
.st-key-cat1 button{ background:#FFF7E2 !important; border-color:#F0B33C !important; }
.st-key-cat1 button[kind="primary"]{ background:linear-gradient(135deg,#FFC847,#E89200) !important; color:#fff !important; border-color:transparent !important; box-shadow:0 5px 14px rgba(232,146,0,.30) !important; }
.st-key-cat2 button{ background:#EAF4FB !important; border-color:#4FB3D9 !important; }
.st-key-cat2 button[kind="primary"]{ background:linear-gradient(135deg,#4FB3D9,#2E86AB) !important; color:#fff !important; border-color:transparent !important; box-shadow:0 5px 14px rgba(46,134,171,.30) !important; }
.st-key-cat3 button{ background:#F1ECFA !important; border-color:#9B82D6 !important; }
.st-key-cat3 button[kind="primary"]{ background:linear-gradient(135deg,#A98FE0,#7857C9) !important; color:#fff !important; border-color:transparent !important; box-shadow:0 5px 14px rgba(120,87,201,.30) !important; }
.st-key-cat4 button{ background:#E9F7EF !important; border-color:#4CBE86 !important; }
.st-key-cat4 button[kind="primary"]{ background:linear-gradient(135deg,#58C98E,#2E9E63) !important; color:#fff !important; border-color:transparent !important; box-shadow:0 5px 14px rgba(46,158,99,.30) !important; }
.st-key-cat5 button{ background:#EEF1F5 !important; border-color:#98A2B3 !important; }
.st-key-cat5 button[kind="primary"]{ background:linear-gradient(135deg,#AAB4C2,#6B7787) !important; color:#fff !important; border-color:transparent !important; box-shadow:0 5px 14px rgba(107,119,135,.30) !important; }

/* 지출 항목 카드 — 휴대폰에서도 항상 2열 유지 (Streamlit 기본 세로 쌓임 방지) */
[data-testid="stHorizontalBlock"]{ display:flex !important; flex-direction:row !important; flex-wrap:nowrap !important; gap:12px !important; }
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]{
  width:calc(50% - 6px) !important; flex:1 1 0 !important; min-width:0 !important; }

/* 폼 박스 — 은은한 블루 톤 + 상단 컬러 액센트 바 */
[data-testid="stForm"]{ position:relative; overflow:hidden;
  background:linear-gradient(180deg,#FFFFFF 0%, #EFF6FE 100%);
  border:1px solid #E2EAF3; border-radius:16px;
  padding:22px 16px 18px; box-shadow:0 6px 18px rgba(30,58,95,0.10); }
[data-testid="stForm"]::before{ content:""; position:absolute; left:0; right:0; top:0; height:5px;
  background:linear-gradient(90deg,#F0A500 0%, #2E86AB 55%, #1E3A5F 100%); }
[data-testid="stForm"] h3{ font-size:18px; margin-bottom:6px; color:var(--cd-navy); }
/* 폼 안 라벨 — 살짝 키우고 또렷하게 */
[data-testid="stForm"] [data-testid="stWidgetLabel"] p{ font-size:15px; color:var(--cd-navy) !important; font-weight:700; }
[data-testid="stAlert"]{ border-radius:12px; font-size:15px; }
[data-testid="stExpander"]{ border-radius:12px; }
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
        st.error(f"🔥 Firebase 초기화 실패: {e}")
        st.stop()

try:
    db = firestore.client()
except Exception as e:
    st.error(f"🔥 Firestore 연결 실패: {e}")
    st.stop()

# ── 현장 목록 불러오기 ──────────────────────
# [수정] 캐시 TTL을 10초로 단축 → 새 현장 등록 후 빠르게 반영
@st.cache_data(ttl=10)
def get_project_list():
    """대표님이 PC에서 등록한 현장 목록을 Firebase에서 가져옵니다."""
    try:
        docs = db.collection('projects').stream()
        return [doc.id for doc in docs]
    except Exception as e:
        st.error(f"DB 연결 오류: {e}")
        return []

project_list = get_project_list()

# ── 모바일 UI 화면 ──────────────────────
st.markdown("""
<div class="cd-mhero">
  <div class="t">📱 현장 지출 간편 등록</div>
  <div class="s">천도글라스 직원 전용 입력 시스템</div>
</div>
""", unsafe_allow_html=True)

if not project_list:
    st.warning("현재 등록된 진행 현장이 없습니다. 사무실에 문의해주세요.")
    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        st.rerun()
else:
    # [수정] 제출 완료 상태 관리 (중복 제출 방지)
    if 'submitted' not in st.session_state:
        st.session_state['submitted'] = False

    # 등록 완료 메시지 표시
    if st.session_state['submitted']:
        st.success("✅ 등록이 완료되었습니다! 새 내역을 입력하려면 아래 버튼을 눌러주세요.")
        if st.button("➕ 새 지출 등록하기", use_container_width=True, type="primary"):
            st.session_state['submitted'] = False
            st.rerun()
    else:
        # ── 지출 항목: 6개 카드 버튼으로 직관 선택 (한 번 탭) ──────────────────────
        # st.form 안에서는 일반 버튼을 못 쓰므로, 항목 카드는 폼 '밖'에서 고르고 결과를 세션에 저장
        if 'category' not in st.session_state:
            st.session_state['category'] = '식대/경비'
        st.markdown("#### 💳 지출 항목 — 눌러서 선택")
        cat_cards = [("식대/경비", "🍱"), ("장비비", "🚜"), ("자재비", "🧱"),
                     ("외주비", "🤝"), ("인건비", "👷"), ("기타", "📦")]
        for r in range(0, len(cat_cards), 2):
            cols = st.columns(2)
            for j, (name, icon) in enumerate(cat_cards[r:r + 2]):
                is_sel = (st.session_state['category'] == name)
                # key=cat0~cat5 → CSS의 .st-key-catN 으로 카드별 색 지정
                if cols[j].button(f"{icon}  {name}", key=f"cat{r + j}", use_container_width=True,
                                  type=("primary" if is_sel else "secondary")):
                    st.session_state['category'] = name
                    st.rerun()

        with st.form("expense_form", clear_on_submit=True):
            # 제목 — 선택한 항목은 색글씨로 강조 (category는 고정 목록이라 안전)
            st.markdown(
                f"<h3>🧾 지출 내역 입력 "
                f"<span style='color:#2E86AB'>· {st.session_state['category']}</span></h3>",
                unsafe_allow_html=True)

            # 1. 날짜 (기본값: 오늘)
            i_date = st.date_input("📅 결제 날짜", datetime.now())

            # 2. 현장 선택 (드롭다운으로 오타 원천 차단)
            target_project = st.selectbox("🏗️ 시공 현장", project_list)

            # 3. 상세 내용
            item_detail = st.text_input("✏️ 상세 내역 (예: 점심 식대, 5톤 지게차)")

            # 4. 작업자 (인건비를 고른 경우에만 표시)
            worker = ""
            if st.session_state['category'] == '인건비':
                worker = st.text_input("👷 작업자 성명")

            # 5. 금액 입력 (모바일 숫자 키보드 팝업)
            amount = st.number_input("💰 결제 금액 (원)", min_value=0, step=10000, format="%d")

            submitted = st.form_submit_button("🚀 등록하기", use_container_width=True)

            if submitted:
                # 선택한 지출 항목(카드)을 사용
                category = st.session_state['category']
                # ── 입력값 검증 ──────────────────────
                if amount <= 0:
                    st.error("⚠️ 결제 금액을 정확히 입력해주세요.")
                elif not item_detail.strip():
                    st.error("⚠️ 상세 내역을 간략히라도 적어주세요.")
                else:
                    try:
                        # [수정] .update() 대신 트랜잭션으로 안전하게 저장
                        project_ref = db.collection('projects').document(target_project)

                        new_expense = {
                            '날짜': str(i_date),
                            '항목': category,
                            '내역': item_detail.strip(),
                            '금액': amount,
                            'worker': worker.strip() if worker else ""
                        }

                        @firestore.transactional
                        def add_expense_transaction(transaction, ref):
                            snapshot = ref.get(transaction=transaction)
                            if snapshot.exists:
                                # 기존 문서에 추가
                                current_expenses = snapshot.to_dict().get('expenses', [])
                                current_expenses.append(new_expense)
                                transaction.update(ref, {'expenses': current_expenses})
                            else:
                                # [수정] 문서가 없는 경우에도 안전하게 생성
                                transaction.set(ref, {
                                    'expenses': [new_expense],
                                    'collections': [],
                                    'plans': [],
                                    'client': '',
                                    'contract': 0
                                })

                        # 트랜잭션 실행
                        transaction = db.transaction()
                        add_expense_transaction(transaction, project_ref)

                        # [수정] 제출 완료 상태로 전환 (중복 제출 방지)
                        st.session_state['submitted'] = True
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ 전송 실패: 네트워크 상태를 확인해주세요. ({e})")

    # ── 하단 도움말 ──────────────────────
    with st.expander("❓ 입력이 안 될 때"):
        st.markdown("""
        - 현장 목록이 비어있으면 **사무실에 연락**해주세요
        - 전송 실패 시 **와이파이/데이터** 확인 후 재시도
        - 같은 내용을 두 번 누르면 **한 건만 등록**됩니다 (정상)
        """)
        if st.button("🔄 현장 목록 새로고침"):
            st.cache_data.clear()
            st.rerun()
