import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json

# ── 모바일 최적화 설정 ──────────────────────
st.set_page_config(page_title="현장 지출", page_icon="🧾", layout="centered", initial_sidebar_state="collapsed")

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
st.title("📱 현장 지출 간편 등록")
st.caption("천도글라스 직원 전용 입력 시스템")

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
        with st.form("expense_form", clear_on_submit=True):
            st.markdown("### 🧾 지출 내역 입력")

            # 1. 날짜 (기본값: 오늘)
            i_date = st.date_input("결제 날짜", datetime.now())

            # 2. 현장 선택 (드롭다운으로 오타 원천 차단)
            target_project = st.selectbox("시공 현장", project_list)

            # 3. 지출 항목 선택 (PC 프로그램과 카테고리 일치)
            cat_list = ["식대/경비", "장비비", "자재비", "외주비", "인건비", "기타"]
            category = st.selectbox("지출 항목", cat_list)

            # 4. 상세 내용 및 작업자
            item_detail = st.text_input("상세 내역 (예: 점심 식대, 5톤 지게차, 주유비)")
            worker = st.text_input("작업자 성명 (인건비인 경우만 입력)")

            # 5. 금액 입력 (모바일 숫자 키보드 팝업)
            amount = st.number_input("결제 금액 (원)", min_value=0, step=10000, format="%d")

            submitted = st.form_submit_button("🚀 등록하기", use_container_width=True)

            if submitted:
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
