from flask import Flask, request, session, redirect, render_template
import os, sqlite3, uuid, hashlib
from dotenv import load_dotenv
from datetime import datetime
import openai
import re

# 환경 설정 불러오기
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BUY_ME_A_COFFEE_LINK = os.getenv("BUY_ME_A_COFFEE_LINK")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecret")

DB_NAME = "fortune.db"

# DB 초기화
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            birthdate TEXT,
            birthhour INTEGER,
            session_token TEXT,
            first_visit TIMESTAMP,
            last_visit TIMESTAMP,
            visit_count INTEGER DEFAULT 1
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_fortunes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            menu TEXT,
            date TEXT,
            result TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 세션 토큰 생성
def generate_session_token(email):
    raw = f"{email}-{str(uuid.uuid4())}"
    return hashlib.sha256(raw.encode()).hexdigest()

def get_today_string():
    return datetime.now().strftime("%Y-%m-%d")

def get_fortune_from_db(email, menu):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT result FROM user_fortunes WHERE email=? AND menu=? AND date=?",
              (email, menu, get_today_string()))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def save_fortune_to_db(email, menu, result):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO user_fortunes (email, menu, date, result) VALUES (?, ?, ?, ?)",
              (email, menu, get_today_string(), result))
    conn.commit()
    conn.close()

# 유저 저장 또는 업데이트
def save_or_update_user(name, email, birthdate, birthhour, session_token):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, visit_count FROM users WHERE email = ? AND session_token = ?", (email, session_token))
    existing = c.fetchone()
    now = datetime.now()
    if existing:
        c.execute("UPDATE users SET last_visit = ?, visit_count = ? WHERE id = ?",
                  (now, existing[1] + 1, existing[0]))
    else:
        c.execute('''
            INSERT INTO users (name, email, birthdate, birthhour, session_token, first_visit, last_visit)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, email, birthdate, birthhour, session_token, now, now))
    conn.commit()
    conn.close()

def format_fortune_text(text):
    # 마침표와 종결 어미 기준으로 문장 분리
    sentences = re.split(r'(?<=[다요]\.)\s*', text.strip())

    result = []
    for sentence in sentences:
        # 중요 키워드 강조
        sentence = re.sub(r'(재물|성공|조심|노력|행운|사랑|건강|위험)', r'<b>\1</b>', sentence)
        if sentence:
            result.append(sentence.strip())

    return '<br><br>'.join(result)

# route: PAGE 1
@app.route("/", methods=["GET", "POST"])
def page1():
    if request.method == "POST":
        birthdate = request.form["birthdate"]
        birthhour = int(request.form["birthhour"])
        gender = request.form["gender"]

        # 생성된 유저 식별용 이메일 (가상)
        email = f"user_{uuid.uuid4().hex[:8]}@nomail.com"
        name = request.form.get("name", "").strip()
        if not name:
            name = "손님"

        session_token = generate_session_token(email)
        session["session_token"] = session_token
        session["email"] = email
        session["name"] = name
        session["gender"] = gender
        session["birthdate"] = birthdate
        session["birthhour"] = birthhour

        save_or_update_user(name, email, birthdate, birthhour, session_token)
        return redirect("/dashboard")
    return render_template("page1.html")

# 천간/지지 계산
heavenly_stems = ['갑', '을', '병', '정', '무', '기', '경', '신', '임', '계']
earthly_branches = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']

def get_ganji(year):
    gan = heavenly_stems[(year - 4) % 10]
    ji = earthly_branches[(year - 4) % 12]
    return gan + ji

def get_hour_branch(hour):
    branches = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']
    index = ((hour + 1) // 2) % 12
    return branches[index]

# 사주 8자 구성 및 오행 매핑
def get_full_saju(birthdate, birth_hour):
    # 한자 음각 정보 (간지)
    heavenly_stems = ['갑', '을', '병', '정', '무', '기', '경', '신', '임', '계']
    earthly_branches = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']

    # 오행 매핑 (한자 + 한글 포함)
    element_map = {
        '갑': ('목', '木'), '을': ('목', '木'),
        '병': ('화', '火'), '정': ('화', '火'),
        '무': ('토', '土'), '기': ('토', '土'),
        '경': ('금', '金'), '신': ('금', '金'),
        '임': ('수', '水'), '계': ('수', '水'),
        '자': ('수', '水'), '축': ('토', '土'),
        '인': ('목', '木'), '묘': ('목', '木'),
        '진': ('토', '土'), '사': ('화', '火'),
        '오': ('화', '火'), '미': ('토', '土'),
        '신': ('금', '金'), '유': ('금', '金'),
        '술': ('토', '土'), '해': ('수', '水'),
    }

    # 년, 월, 일, 시 간지 계산 (현재는 년, 시지만 확장 가능)
    year = birthdate.year
    hour = birth_hour

    year_ganji = heavenly_stems[(year - 4) % 10] + earthly_branches[(year - 4) % 12]
    hour_branch = get_hour_branch(hour)

    # 오행 카운트
    elements = [element_map[char][0] for char in year_ganji]
    elements.append(element_map[hour_branch][0])

    counts = {"목": 0, "화": 0, "토": 0, "금": 0, "수": 0}
    for el in elements:
        counts[el] += 1

    return {
        "year_ganji": year_ganji,
        "hour_branch": hour_branch,
        "elements": elements,
        "counts": counts
    }

# GPT 운세 생성 함수 (기본)
def generate_fortune(birthdate, birth_hour):
    year = birthdate.year
    year_ganji = get_ganji(year)
    hour_branch = get_hour_branch(birth_hour)

    prompt = f"""
당신은 사주 해석 전문가입니다.
아래 사용자의 연간지: {year_ganji}, 시지: {hour_branch}를 바탕으로
오늘의 전반적인 운세를 300자 이내로 자연스럽게 설명해주세요.
    """

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "당신은 정확한 사주 운세 전문가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=600
        )
        reply = response.choices[0].message.content
        return format_fortune_text(reply)
    except Exception as e:
        return f"⚠️ 오류 발생: {e}"

# GPT 사주팔자 해석 함수
def generate_saju_analysis(birthdate, birth_hour):
    saju = get_full_saju(birthdate, birth_hour)

    # 오행 개수 한글 + 한자 형태로 정리
    element_lines = []
    for k, v in saju["counts"].items():
        hanja = {'목': '木', '화': '火', '토': '土', '금': '金', '수': '水'}[k]
        element_lines.append(f"- {k}({hanja}): {v}개")
    element_text = "\n".join(element_lines)

    prompt = f"""
당신은 명리학을 기반으로 해석하는 전문 사주 상담가입니다.

다음은 한 사용자의 사주 정보입니다:

- 연간지: {saju['year_ganji']}
- 시지: {saju['hour_branch']}
- 오행 분포:
{element_text}

이 사주의 오행 구성과 강약을 바탕으로, 이 사람의 성격적 특징, 재물운, 인생 흐름에 대해 300자 이내로 명료하고 따뜻하게 설명해주세요.
전문가의 조언처럼 신뢰감 있게 작성해주세요.
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "당신은 정확한 사주 해석 전문가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.85,
            max_tokens=600
        )
        reply = response.choices[0].message.content
        return format_fortune_text(reply)
    except Exception as e:
        return f"⚠️ 오류 발생: {e}"

# route: PAGE 2
@app.route("/dashboard")
def page2():
    if "session_token" not in session:
        return redirect("/")

    name = session.get("name", "손님")
    email = session.get("email")
    birthdate_str = session.get("birthdate")
    birth_hour = int(session.get("birthhour", 12))

    try:
        birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d")
    except:
        birthdate = datetime.now()

    # Generate or retrieve today’s fortune
    cached = get_fortune_from_db(email, "basic")
    if cached:
        today_fortune = cached
    else:
        today_fortune = generate_fortune(birthdate, birth_hour)
        save_fortune_to_db(email, "basic", today_fortune)

    # Generate saju analysis with caching
    cached_saju = get_fortune_from_db(email, "saju")
    if cached_saju:
        saju_analysis = cached_saju
    else:
        saju_analysis = generate_saju_analysis(birthdate, birth_hour)
        save_fortune_to_db(email, "saju", saju_analysis)

    return render_template(
        "page2.html",
        name=name,
        today_fortune=today_fortune,
        saju_analysis=saju_analysis,
        coffee_link=BUY_ME_A_COFFEE_LINK
    )

# route: PAGE 3
@app.route("/result/<menu>")
def page3(menu):
    if "session_token" not in session:
        return redirect("/")

    menu_titles = {
        "love": "연애운 💘",
        "money": "재물운 💰",
        "health": "건강운 💪",
        "match": "궁합 🔗",
        "mission": "인생 미션 🎯"
    }
    menu_title = menu_titles.get(menu, "운세")

    prompt = f"""
당신은 운세 해석 전문가입니다.
아래 사용자의 사주 기반으로 "{menu_title}" 항목에 대한 운세를 300자 이내로 알려주세요.
항목: {menu_title}
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "당신은 정확한 사주 운세 전문가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=600
        )
        fortune_result = format_fortune_text(response.choices[0].message.content)
    except Exception as e:
        fortune_result = f"⚠️ 오류 발생: {e}"

    return render_template("page3.html", menu_title=menu_title, fortune_result=fortune_result)

# route: AJAX fortune results
@app.route("/api/fortune/<menu>")
def api_fortune(menu):
    if "session_token" not in session:
        return {"error": "unauthorized"}, 401

    email = session.get("email")
    menu_titles = {
        "love": "연애운 💘",
        "money": "재물운 💰",
        "health": "건강운 💪",
        "match": "궁합 🔗",
        "mission": "인생 미션 🎯",
        "today": "오늘의 운세 🌟"
    }
    menu_title = menu_titles.get(menu, "운세")

    birthdate_str = session.get("birthdate")
    birth_hour = int(session.get("birthhour", 12))
    birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d")

    if menu == "today":
        result = generate_fortune(birthdate, birth_hour)
        return {"menu_title": menu_titles[menu], "fortune_result": result}

    cached = get_fortune_from_db(email, menu)
    if cached:
        return {"menu_title": menu_title, "fortune_result": cached}

    prompt = f"""
    당신은 운세 해석 전문가입니다.
    사용자의 사주 정보를 기반으로 "{menu_title}" 항목에 대해 300자 이내로 자연스럽게 운세를 알려주세요.
    항목: {menu_title}
    """

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "당신은 정확한 사주 운세 전문가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=600
        )
        fortune_result = format_fortune_text(response.choices[0].message.content)
    except Exception as e:
        fortune_result = f"⚠️ 오류 발생: {e}"

    save_fortune_to_db(email, menu, fortune_result)
    return {"menu_title": menu_title, "fortune_result": fortune_result}

@app.route("/match_result")
def match_result():
    your_name = request.args.get("yourName")
    your_birth = request.args.get("yourBirth")
    partner_name = request.args.get("partnerName")
    partner_birth = request.args.get("partnerBirth")

    prompt = f"""
당신은 연애궁합 전문가입니다.
아래 두 사람의 이름과 생년월일을 참고하여, 이들의 궁합 점수를 100점 만점으로 평가하고,
간단한 이유와 함께 결과를 300자 이내로 알려주세요.

이름1: {your_name}, 생일1: {your_birth}
이름2: {partner_name}, 생일2: {partner_birth}

결과는 다음 형식을 지켜주세요:

궁합 점수: XX점
설명: (두 사람의 성향이나 관계 흐름을 중심으로)
      """

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "당신은 연애 궁합 전문 운세 상담가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=600
        )
        result = format_fortune_text(response.choices[0].message.content)
    except Exception as e:
        result = f"⚠️ 오류 발생: {e}"

    return render_template("match_result.html", result=result)

if __name__ == "__main__":
    app.run(debug=True)