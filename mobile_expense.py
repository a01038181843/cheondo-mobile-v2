import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

# [모바일 최적화 설정] 화면을 꽉 채우고 사이드바를 숨깁니다.
st.set_page_config(page_title="천도글라스 현장 지출", layout="centered", initial_sidebar_state="collapsed")

# --- [파이어베이스 연결] 스트림릿 비밀 금고에서 열쇠를 꺼냅니다 ---
import json
if not firebase_admin._apps:
    # 비밀 금고(secrets)에 숨겨둔 텍스트를 가져와서 딕셔너리로 변환합니다.
    key_dict = json.loads(st.secrets["firebase_key"])
    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred)
db = firestore.client()# --- [현장 목록 실시간 불러오기] ---
# 대표님이 PC에서 등록한 현장 목록만 가져옵니다.
@st.cache_data(ttl=60) # 데이터 절약을 위해 1분마다 새로고침
def get_project_list():
    try:
        docs = db.collection('projects').stream()
        return [doc.id for doc in docs]
    except Exception as e:
        st.error(f"DB 연결 오류: {e}")
        return []

project_list = get_project_list()

# --- [모바일 UI 화면] ---
st.title("📱 현장 지출 간편 등록")
st.caption("천도글라스 직원 전용 입력 시스템")

if not project_list:
    st.warning("현재 등록된 진행 현장이 없습니다. 사무실에 문의해주세요.")
else:
    # 폼(Form)을 사용하여 묶어서 한 번에 전송합니다.
    with st.form("expense_form", clear_on_submit=True):
        st.markdown("### 🧾 지출 내역 입력")

        # 1. 날짜 (기본값: 오늘)
        i_date = st.date_input("결제 날짜", datetime.now())

        # 2. 현장 선택 (드롭다운으로 오타 원천 차단)
        target_project = st.selectbox("시공 현장", project_list)

        # 3. 항목 선택
        # PC 프로그램과 통계를 맞추기 위해 카테고리를 일치시킵니다.
        cat_list = ["식대/경비", "장비비", "자재비", "외주비", "인건비", "기타"]
        category = st.selectbox("지출 항목", cat_list)

        # 4. 상세 내용 및 작업자
        item_detail = st.text_input("상세 내역 (예: 점심 식대, 5톤 지게차, 주유비)")
        worker = st.text_input("작업자 성명 (인건비인 경우만 입력)")

        # 5. 금액 입력 (모바일 숫자 키보드 팝업)
        amount = st.number_input("결제 금액 (원)", min_value=0, step=10000, format="%d")

        # 모바일 환경을 고려한 큼직한 전송 버튼
        submitted = st.form_submit_button("🚀 등록하기", use_container_width=True)

        if submitted:
            # --- [오류 변수 완벽 통제 로직] ---
            if amount <= 0:
                st.error("⚠️ 결제 금액을 정확히 입력해주세요.")
            elif not item_detail:
                st.error("⚠️ 상세 내역을 간략히라도 적어주세요.")
            else:
                try:
                    # 선택된 현장 문서(Document) 지정
                    project_ref = db.collection('projects').document(target_project)
                    
                    # PC 프로그램(cost_manager.py)이 인식할 수 있는 동일한 딕셔너리 구조
                    new_expense = {
                        '날짜': str(i_date),
                        '항목': category,
                        '내역': item_detail,
                        '금액': amount,
                        'worker': worker if worker else ""
                    }

                    # [핵심 오류 대비] 동시 접속 데이터 증발 방지
                    # 여러 직원이 동시에 입력해도 덮어쓰지 않고 안전하게 '추가'만 하도록 ArrayUnion 사용
                    project_ref.update({
                        'expenses': firestore.ArrayUnion([new_expense])
                    })

                    st.success(f"✅ [{target_project}] 현장에 {amount:,}원이 성공적으로 등록되었습니다!")
                    st.balloons()
                except Exception as e:
                    st.error(f"❌ 전송 실패: 네트워크 상태를 확인해주세요. ({e})")