
from flask import Flask, request, session, redirect, render_template
import os, sqlite3, uuid, hashlib
from dotenv import load_dotenv
from datetime import datetime, timedelta
import openai
import re
import sxtwl

# --- 三命通会 원문 해석 (ctext) 유틸리티 함수 ---
def normalize_section_key(day_pillar, hour_pillar):
    # 예: '己丑日' + '甲子' => '六己日甲子时断'
    day_stem = day_pillar[0]
    hour_branch = hour_pillar[1]
    return f"六{day_stem}日{hour_branch}时断"

def get_ctext_match(day_pillar, hour_pillar):
    keyword1 = f"{day_pillar}日{hour_pillar}"     # ex: 丙寅日癸巳
    keyword2 = f"{day_pillar[0]}日{hour_pillar}"  # ex: 丙日癸巳
    conn = sqlite3.connect("ctext.db")
    c = conn.cursor()
    c.execute("SELECT content, kr_literal FROM wiki_content WHERE content LIKE ? OR content LIKE ?", 
              (f"%{keyword1}%", f"%{keyword2}%"))
    rows = c.fetchall()
    conn.close()
    return [{"content": r[0], "kr_literal": r[1]} for r in rows if r[0]] if rows else None

# 환경 설정 불러오기
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
BUY_ME_A_COFFEE_LINK = os.getenv("BUY_ME_A_COFFEE_LINK")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretpowerisaigo!")

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
    c.execute('''
        CREATE TABLE IF NOT EXISTS saju_interpretations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type INTEGER,
            ilju TEXT,
            cn TEXT,
            kr TEXT,
            en TEXT
        )
    ''')
    conn.commit()
    # CSV에서 사주 해석 불러오기 및 삽입
    import csv
    csv_path = "ilju_db.csv"
    c.execute("SELECT COUNT(*) FROM saju_interpretations")
    existing_count = c.fetchone()[0]

    if existing_count == 0 and os.path.exists(csv_path):
        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if len(row) < 5:
                    continue  # 잘못된 행은 건너뜀
                row = [item.strip() for item in row]
                if row[0].startswith('\ufeff'):
                    row[0] = row[0].replace('\ufeff', '')
                type_str, ilju, cn, kr, en = row
                c.execute('''
                    INSERT INTO saju_interpretations (type, ilju, cn, kr, en)
                    VALUES (?, ?, ?, ?, ?)
                ''', (int(type_str), ilju, cn, kr, en))
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
    # Set default values for selects
    default_year = 1984
    default_month = 6
    default_day = 1
    if request.method == "POST":
        year = int(request.form["birth_year"])
        month = int(request.form["birth_month"])
        day = int(request.form["birth_day"])
        birthdate = f"{year:04d}-{month:02d}-{day:02d}"
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
    # Pass defaults for select elements to the template for GET
    return render_template("page1.html",
                           default_year=default_year,
                           default_month=default_month,
                           default_day=default_day)


# 천간/지지 계산 (중국 한자)
heavenly_stems = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸']
earthly_branches = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥']

GAN = heavenly_stems
ZHI = earthly_branches

def get_hour_branch(hour):
    branches = earthly_branches
    index = ((hour + 1) // 2) % 12
    return branches[index]

def calculate_four_pillars(dt: datetime) -> dict:
    day = sxtwl.fromSolar(dt.year, dt.month, dt.day)
    y_gz = day.getYearGZ(False)
    m_gz = day.getMonthGZ()
    d_gz = day.getDayGZ()
    h_gz = day.getHourGZ(dt.hour)

    return {
        "year": GAN[y_gz.tg] + ZHI[y_gz.dz],
        "month": GAN[m_gz.tg] + ZHI[m_gz.dz],
        "day": GAN[d_gz.tg] + ZHI[d_gz.dz],
        "hour": GAN[h_gz.tg] + ZHI[h_gz.dz],
    }

# ====== 사주 상세 계산 함수 및 테이블 ======
# 오행 매핑 (중국 한자)
element_map = {
    '甲': ('목', '木'), '乙': ('목', '木'),
    '丙': ('화', '火'), '丁': ('화', '火'),
    '戊': ('토', '土'), '己': ('토', '土'),
    '庚': ('금', '金'), '辛': ('금', '金'),
    '壬': ('수', '水'), '癸': ('수', '水'),
    '子': ('수', '水'), '丑': ('토', '土'),
    '寅': ('목', '木'), '卯': ('목', '木'),
    '辰': ('토', '土'), '巳': ('화', '火'),
    '午': ('화', '火'), '未': ('토', '土'),
    '申': ('금', '金'), '酉': ('금', '金'),
    '戌': ('토', '土'), '亥': ('수', '水'),
}


# === 십성(십신, Ten Gods) 계산: 오행과 음양 모두 반영 ===
# Updated Ten God computation logic based on 십성의 음양오행 관계.

# 천간을 오행/음양으로 변환
def stem_to_element_yinyang(stem):
    """
    천간(甲, 乙, ...)을 오행(wood, fire, earth, metal, water)과 음양(yang, yin)으로 변환
    """
    mapping = {
        '甲': ('wood', 'yang'), '乙': ('wood', 'yin'),
        '丙': ('fire', 'yang'), '丁': ('fire', 'yin'),
        '戊': ('earth', 'yang'), '己': ('earth', 'yin'),
        '庚': ('metal', 'yang'), '辛': ('metal', 'yin'),
        '壬': ('water', 'yang'), '癸': ('water', 'yin'),
    }
    return mapping.get(stem, ('?', '?'))

# 십성 매핑: (일간 오행, 일간 음양, 비교 오행, 비교 음양) => 십성
TEN_GOD_MAP = {
    # 木(양)
    ('wood', 'yang', 'wood', 'yang'): '비견',
    ('wood', 'yang', 'wood', 'yin'): '겁재',
    ('wood', 'yang', 'fire', 'yang'): '식신',
    ('wood', 'yang', 'fire', 'yin'): '상관',
    ('wood', 'yang', 'earth', 'yang'): '편재',
    ('wood', 'yang', 'earth', 'yin'): '정재',
    ('wood', 'yang', 'metal', 'yang'): '편관',
    ('wood', 'yang', 'metal', 'yin'): '정관',
    ('wood', 'yang', 'water', 'yang'): '편인',
    ('wood', 'yang', 'water', 'yin'): '정인',
    # 木(음)
    ('wood', 'yin', 'wood', 'yang'): '겁재',
    ('wood', 'yin', 'wood', 'yin'): '비견',
    ('wood', 'yin', 'fire', 'yang'): '상관',
    ('wood', 'yin', 'fire', 'yin'): '식신',
    ('wood', 'yin', 'earth', 'yang'): '정재',
    ('wood', 'yin', 'earth', 'yin'): '편재',
    ('wood', 'yin', 'metal', 'yang'): '정관',
    ('wood', 'yin', 'metal', 'yin'): '편관',
    ('wood', 'yin', 'water', 'yang'): '정인',
    ('wood', 'yin', 'water', 'yin'): '편인',
    # 火(양)
    ('fire', 'yang', 'wood', 'yang'): '정인',
    ('fire', 'yang', 'wood', 'yin'): '편인',
    ('fire', 'yang', 'fire', 'yang'): '비견',
    ('fire', 'yang', 'fire', 'yin'): '겁재',
    ('fire', 'yang', 'earth', 'yang'): '식신',
    ('fire', 'yang', 'earth', 'yin'): '상관',
    ('fire', 'yang', 'metal', 'yang'): '편재',
    ('fire', 'yang', 'metal', 'yin'): '정재',
    ('fire', 'yang', 'water', 'yang'): '편관',
    ('fire', 'yang', 'water', 'yin'): '정관',
    # 火(음)
    ('fire', 'yin', 'wood', 'yang'): '편인',
    ('fire', 'yin', 'wood', 'yin'): '정인',
    ('fire', 'yin', 'fire', 'yang'): '겁재',
    ('fire', 'yin', 'fire', 'yin'): '비견',
    ('fire', 'yin', 'earth', 'yang'): '상관',
    ('fire', 'yin', 'earth', 'yin'): '식신',
    ('fire', 'yin', 'metal', 'yang'): '정재',
    ('fire', 'yin', 'metal', 'yin'): '편재',
    ('fire', 'yin', 'water', 'yang'): '정관',
    ('fire', 'yin', 'water', 'yin'): '편관',
    # 土(양)
    ('earth', 'yang', 'wood', 'yang'): '편관',
    ('earth', 'yang', 'wood', 'yin'): '정관',
    ('earth', 'yang', 'fire', 'yang'): '정인',
    ('earth', 'yang', 'fire', 'yin'): '편인',
    ('earth', 'yang', 'earth', 'yang'): '비견',
    ('earth', 'yang', 'earth', 'yin'): '겁재',
    ('earth', 'yang', 'metal', 'yang'): '식신',
    ('earth', 'yang', 'metal', 'yin'): '상관',
    ('earth', 'yang', 'water', 'yang'): '편재',
    ('earth', 'yang', 'water', 'yin'): '정재',
    # 土(음)
    ('earth', 'yin', 'wood', 'yang'): '정관',
    ('earth', 'yin', 'wood', 'yin'): '편관',
    ('earth', 'yin', 'fire', 'yang'): '편인',
    ('earth', 'yin', 'fire', 'yin'): '정인',
    ('earth', 'yin', 'earth', 'yang'): '겁재',
    ('earth', 'yin', 'earth', 'yin'): '비견',
    ('earth', 'yin', 'metal', 'yang'): '상관',
    ('earth', 'yin', 'metal', 'yin'): '식신',
    ('earth', 'yin', 'water', 'yang'): '정재',
    ('earth', 'yin', 'water', 'yin'): '편재',
    # 金(양)
    ('metal', 'yang', 'wood', 'yang'): '정재',
    ('metal', 'yang', 'wood', 'yin'): '편재',
    ('metal', 'yang', 'fire', 'yang'): '편관',
    ('metal', 'yang', 'fire', 'yin'): '정관',
    ('metal', 'yang', 'earth', 'yang'): '정인',
    ('metal', 'yang', 'earth', 'yin'): '편인',
    ('metal', 'yang', 'metal', 'yang'): '비견',
    ('metal', 'yang', 'metal', 'yin'): '겁재',
    ('metal', 'yang', 'water', 'yang'): '식신',
    ('metal', 'yang', 'water', 'yin'): '상관',
    # 金(음)
    ('metal', 'yin', 'wood', 'yang'): '편재',
    ('metal', 'yin', 'wood', 'yin'): '정재',
    ('metal', 'yin', 'fire', 'yang'): '정관',
    ('metal', 'yin', 'fire', 'yin'): '편관',
    ('metal', 'yin', 'earth', 'yang'): '편인',
    ('metal', 'yin', 'earth', 'yin'): '정인',
    ('metal', 'yin', 'metal', 'yang'): '겁재',
    ('metal', 'yin', 'metal', 'yin'): '비견',
    ('metal', 'yin', 'water', 'yang'): '상관',
    ('metal', 'yin', 'water', 'yin'): '식신',
    # 水(양)
    ('water', 'yang', 'wood', 'yang'): '상관',
    ('water', 'yang', 'wood', 'yin'): '식신',
    ('water', 'yang', 'fire', 'yang'): '정재',
    ('water', 'yang', 'fire', 'yin'): '편재',
    ('water', 'yang', 'earth', 'yang'): '편관',
    ('water', 'yang', 'earth', 'yin'): '정관',
    ('water', 'yang', 'metal', 'yang'): '정인',
    ('water', 'yang', 'metal', 'yin'): '편인',
    ('water', 'yang', 'water', 'yang'): '비견',
    ('water', 'yang', 'water', 'yin'): '겁재',
    # 水(음)
    ('water', 'yin', 'wood', 'yang'): '식신',
    ('water', 'yin', 'wood', 'yin'): '상관',
    ('water', 'yin', 'fire', 'yang'): '편재',
    ('water', 'yin', 'fire', 'yin'): '정재',
    ('water', 'yin', 'earth', 'yang'): '정관',
    ('water', 'yin', 'earth', 'yin'): '편관',
    ('water', 'yin', 'metal', 'yang'): '편인',
    ('water', 'yin', 'metal', 'yin'): '정인',
    ('water', 'yin', 'water', 'yang'): '겁재',
    ('water', 'yin', 'water', 'yin'): '비견',
}

# 십성 계산 함수 (오행과 음양 기반)
def get_ten_god(day_stem, compare_stem):
    """
    Return the Ten God (십성) between day_stem and compare_stem
    """
    self_element, self_yin_yang = stem_to_element_yinyang(day_stem)
    other_element, other_yin_yang = stem_to_element_yinyang(compare_stem)
    return TEN_GOD_MAP.get((self_element, self_yin_yang, other_element, other_yin_yang), '')

# 십이신살 (지살, 천살, 월살, 망신, 장성, 반안, 육해, 화개 등)
twelve_gods_table = {
    "寅午戌": ["亥", "子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌"],
    "巳酉丑": ["寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥", "子", "丑"],
    "申子辰": ["巳", "午", "未", "申", "酉", "戌", "亥", "子", "丑", "寅", "卯", "辰"],
    "亥卯未": ["申", "酉", "戌", "亥", "子", "丑", "寅", "卯", "辰", "巳", "午", "未"]
}
twelve_gods_labels = [
    "지살", "천살", "역마", "육해", "화개", "겁살",
    "재살", "천역마", "월살", "망신", "장성", "반안"
]

def get_twelve_gods_group(zhi):  # 일지 기준으로 해당 그룹 반환
    for group, order in twelve_gods_table.items():
        if zhi in group:
            return group, order
    return None, []
    
def get_twelve_gods_by_day_branch(day_branch):
    result = {}
    group, order = get_twelve_gods_group(day_branch)
    if not order:
        return result
    for i, label in enumerate(twelve_gods_labels):
        result[label] = order[i]
    return result

# 역방향 십이신살 매핑 (내 지지가 어떤 신살에 해당하는가)
reverse_twelve_gods_table = {
    '寅午戌': {
        '亥': '지살', '子': '천살', '丑': '역마', '寅': '육해', '卯': '화개', '辰': '겁살',
        '巳': '재살', '午': '천역마', '未': '월살', '申': '망신', '酉': '장성', '戌': '반안'
    },
    '申子辰': {
        '巳': '지살', '午': '천살', '未': '역마', '申': '육해', '酉': '화개', '戌': '겁살',
        '亥': '재살', '子': '천역마', '丑': '월살', '寅': '망신', '卯': '장성', '辰': '반안'
    },
    '亥卯未': {
        '申': '지살', '酉': '천살', '戌': '역마', '亥': '육해', '子': '화개', '丑': '겁살',
        '寅': '재살', '卯': '천역마', '辰': '월살', '巳': '망신', '午': '장성', '未': '반안'
    },
    '巳酉丑': {
        '寅': '지살', '卯': '천살', '辰': '역마', '巳': '육해', '午': '화개', '未': '겁살',
        '申': '재살', '酉': '천역마', '戌': '월살', '亥': '망신', '子': '장성', '丑': '반안'
    }
}

def get_my_twelve_god(zhi, day_branch):
    for group, mapping in reverse_twelve_gods_table.items():
        if day_branch in group:
            return mapping.get(zhi)
    return None

# 십이운성 표 (일간-지지)
twelve_stage_table = {
    '甲': {'子': '절', '丑': '태', '寅': '양', '卯': '장생', '辰': '목욕', '巳': '관대', '午': '건록', '未': '제왕', '申': '쇠', '酉': '병', '戌': '사', '亥': '묘'},
    '乙': {'子': '묘', '丑': '절', '寅': '태', '卯': '양', '辰': '장생', '巳': '목욕', '午': '관대', '未': '건록', '申': '제왕', '酉': '쇠', '戌': '병', '亥': '사'},
    '丙': {'寅': '장생', '卯': '목욕', '辰': '관대', '巳': '건록', '午': '제왕', '未': '쇠', '申': '병', '酉': '사', '戌': '묘', '亥': '절', '子': '태', '丑': '양'},
    '丁': {'寅': '묘', '卯': '장생', '辰': '목욕', '巳': '관대', '午': '건록', '未': '제왕', '申': '쇠', '酉': '병', '戌': '사', '亥': '묘', '子': '절', '丑': '태'},
    '戊': {'巳': '장생', '午': '목욕', '未': '관대', '申': '건록', '酉': '제왕', '戌': '쇠', '亥': '병', '子': '사', '丑': '묘', '寅': '절', '卯': '태', '辰': '양'},
    '己': {'巳': '묘', '午': '장생', '未': '목욕', '申': '관대', '酉': '건록', '戌': '제왕', '亥': '쇠', '子': '병', '丑': '사', '寅': '묘', '卯': '절', '辰': '태'},
    '庚': {'申': '장생', '酉': '목욕', '戌': '관대', '亥': '건록', '子': '제왕', '丑': '쇠', '寅': '병', '卯': '사', '辰': '묘', '巳': '절', '午': '태', '未': '양'},
    '辛': {'申': '묘', '酉': '장생', '戌': '목욕', '亥': '관대', '子': '건록', '丑': '제왕', '寅': '쇠', '卯': '병', '辰': '사', '巳': '묘', '午': '절', '未': '태'},
    '壬': {'亥': '장생', '子': '목욕', '丑': '관대', '寅': '건록', '卯': '제왕', '辰': '쇠', '巳': '병', '午': '사', '未': '묘', '申': '절', '酉': '태', '戌': '양'},
    '癸': {'亥': '묘', '子': '장생', '丑': '목욕', '寅': '관대', '卯': '건록', '辰': '제왕', '巳': '쇠', '午': '병', '未': '사', '申': '묘', '酉': '절', '戌': '태'},
}


# 십이운성 계산 함수
def get_twelve_stage(day_gan, branch):
    return twelve_stage_table.get(day_gan, {}).get(branch, '')

# 사주 각 기둥에 대한 세부 정보 정리
def get_saju_details(pillars):
    day_gan = pillars['day'][0]  # 일간 기준
    saju_info = {}

    # 전체 지장간(藏干) 매핑 (전통적 사주용, 모든 지지에 대해 배열로 제공)
    hidden_gan_dict = {
        '子': ['癸'],
        '丑': ['己', '癸', '辛'],
        '寅': ['甲', '丙', '戊'],
        '卯': ['乙'],
        '辰': ['戊', '乙', '癸'],
        '巳': ['丙', '戊', '庚'],
        '午': ['丁', '己'],
        '未': ['己', '丁', '乙'],
        '申': ['庚', '壬', '戊'],
        '酉': ['辛'],
        '戌': ['戊', '辛', '丁'],
        '亥': ['壬', '甲']
    }

    for pillar_name in ['year', 'month', 'day', 'hour']:
        gan = pillars[pillar_name][0]
        zhi = pillars[pillar_name][1]
        el_gan, yin_gan = element_map.get(gan, ('?', '?'))  # 한글 간지용
        el_zhi, yin_zhi = element_map.get(zhi, ('?', '?'))
        # 십성(ten_god) 계산을 모든 천간에 대해, 일간 기준으로 수행 (음양오행 기반)
        ten_god = get_ten_god(day_gan, gan)
        # 지지의 모든 지장간(藏干)으로 십성 계산 (음양오행 기반)
        hidden_gans = hidden_gan_dict.get(zhi, [])
        ten_god_zhi = [get_ten_god(day_gan, hg) for hg in hidden_gans]
        twelve_stage = get_twelve_stage(day_gan, zhi)
        twelve_god = get_my_twelve_god(zhi, pillars['day'][1])

        saju_info[pillar_name] = {
            'gan': gan,
            'zhi': zhi,
            'element_gan': el_gan,
            'yin_gan': yin_gan,
            'element_zhi': el_zhi,
            'yin_zhi': yin_zhi,
            'ten_god': ten_god,
            'ten_god_zhi': ', '.join(ten_god_zhi),
            'twelve_stage': twelve_stage,
            'twelve_god': twelve_god
        }

    return saju_info


# --- SajuAnalyzer class implementation (moved up) ---
class SajuAnalyzer:
    """
    간단한 사주 분석 클래스 (예시 버전)
    """
    def __init__(self):
        # 오행 매핑
        self.element_map = {
            '甲': '목', '乙': '목',
            '丙': '화', '丁': '화',
            '戊': '토', '己': '토',
            '庚': '금', '辛': '금',
            '壬': '수', '癸': '수',
            '子': '수', '丑': '토',
            '寅': '목', '卯': '목',
            '辰': '토', '巳': '화',
            '午': '화', '未': '토',
            '申': '금', '酉': '금',
            '戌': '토', '亥': '수',
        }
        self.elements_kr = ['목', '화', '토', '금', '수']

    def analyze_saju(self, year_pillar, month_pillar, day_pillar, time_pillar):
        """
        네 기둥(연, 월, 일, 시)의 간지(예: '甲子')를 입력받아
        오행 분포와 간단한 해석을 반환합니다.
        """
        # 각 기둥에서 천간과 지지 추출
        pillars = [year_pillar, month_pillar, day_pillar, time_pillar]
        chars = []
        for p in pillars:
            if len(p) == 2:
                chars.extend([p[0], p[1]])
        # 오행 카운트
        counts = {el: 0 for el in self.elements_kr}
        for ch in chars:
            el = self.element_map.get(ch)
            if el:
                counts[el] += 1
        # 간단한 해석
        max_el = max(counts, key=lambda k: counts[k])
        min_el = min(counts, key=lambda k: counts[k])
        max_val = counts[max_el]
        min_val = counts[min_el]
        # 해석 문구(예시)
        analysis = f"오행 분포: " + ", ".join([f"{k}:{v}" for k,v in counts.items()])
        if max_val - min_val >= 2:
            analysis += f"<br>가장 강한 오행은 <b>{max_el}</b>({max_val}개), 가장 약한 오행은 <b>{min_el}</b>({min_val}개)입니다.<br>"
            analysis += f"{max_el}의 기운이 두드러지므로, {max_el}의 특성을 잘 살리고 {min_el}의 기운을 보완하면 좋겠습니다."
        else:
            analysis += "<br>오행의 균형이 비교적 잘 잡혀 있습니다."

        # 추가: 십성 계산
        ten_gods = []
        day_gan = day_pillar[0]
        for label, pillar in zip(['년간', '월간', '일간', '시간'], [year_pillar, month_pillar, day_pillar, time_pillar]):
            tg = get_ten_god(day_gan, pillar[0])
            ten_gods.append(f"- {label} {pillar[0]}: {tg}")
        for label, pillar in zip(['년지', '월지', '일지', '시지'], [year_pillar, month_pillar, day_pillar, time_pillar]):
            zhi = pillar[1]
            main_hidden_gan = {
                '子': '癸', '丑': '己', '寅': '甲', '卯': '乙', '辰': '戊', '巳': '丙',
                '午': '丁', '未': '己', '申': '庚', '酉': '辛', '戌': '戊', '亥': '壬'
            }
            hidden_g = main_hidden_gan.get(zhi)
            if hidden_g:
                tg = get_ten_god(day_gan, hidden_g)
                ten_gods.append(f"- {label} {zhi}: {tg}")

        return analysis

# Analyze saju using SajuAnalyzer class
def analyze_saju_by_saju_analyzer(year_pillar, month_pillar, day_pillar, time_pillar):
    analyzer = SajuAnalyzer()
    return analyzer.analyze_saju(year_pillar, month_pillar, day_pillar, time_pillar)

# GPT 운세 생성 함수 (기본)
def generate_fortune(birthdate, birth_hour):
    year = birthdate.year
    year_ganji = GAN[(year - 4) % 10] + ZHI[(year - 4) % 12]
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
    # Use year_ganji and hour_branch as in generate_fortune for consistency
    year = birthdate.year
    year_ganji = GAN[(year - 4) % 10] + ZHI[(year - 4) % 12]
    hour_branch = get_hour_branch(birth_hour)
    # 오행 카운트 (year_ganji + hour_branch)
    elements = [element_map[char][0] for char in year_ganji]
    elements.append(element_map[hour_branch][0])
    counts = {"목": 0, "화": 0, "토": 0, "금": 0, "수": 0}
    for el in elements:
        counts[el] += 1
    # 오행 개수 한글 + 한자 형태로 정리
    element_lines = []
    for k, v in counts.items():
        hanja = {'목': '木', '화': '火', '토': '土', '금': '金', '수': '水'}[k]
        element_lines.append(f"- {k}({hanja}): {v}개")
    element_text = "\n".join(element_lines)

    prompt = f"""
당신은 명리학을 기반으로 해석하는 전문 사주 상담가입니다.

다음은 한 사용자의 사주 정보입니다:

- 연간지: {year_ganji}
- 시지: {hour_branch}
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

def get_ilju_interpretation(ilju):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT cn, kr, en FROM saju_interpretations WHERE ilju = ?", (ilju,))
    row = c.fetchone()
    conn.close()
    if row:
        # Apply newline-to-<br> conversion to explanations
        cn = row[0].replace('\n', '<br>') if row[0] else None
        kr = row[1].replace('\n', '<br>') if row[1] else None
        en = row[2].replace('\n', '<br>') if row[2] else None
        return {"cn": cn, "kr": kr, "en": en}
    else:
        return {"cn": None, "kr": None, "en": None}

# route: PAGE 2
@app.route("/dashboard")
def page2():
    if "session_token" not in session:
        return redirect("/")

    name = session.get("name", "손")
    email = session.get("email")
    birthdate_str = session.get("birthdate")
    birth_hour = int(session.get("birthhour", 12))

    try:
        birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d")
    except:
        birthdate = datetime.now()

    # Generate or retrieve today’s fortune
    # cached = get_fortune_from_db(email, "basic")
    # if cached:
    #     today_fortune = cached
    # else:
    #     today_fortune = generate_fortune(birthdate, birth_hour)
    #     save_fortune_to_db(email, "basic", today_fortune)

    # Generate saju analysis with caching
    # cached_saju = get_fortune_from_db(email, "saju")
    # if cached_saju:
    #     saju_analysis = cached_saju
    # else:
    #     saju_analysis = generate_saju_analysis(birthdate, birth_hour)
    #     save_fortune_to_db(email, "saju", saju_analysis)

    # 일주 계산 및 해석 추가
    pillars = calculate_four_pillars(datetime(birthdate.year, birthdate.month, birthdate.day, birth_hour))
    saju_info = get_saju_details(pillars)
    ilju = pillars["day"]
    ilju_interpretation = get_ilju_interpretation(ilju)

    saju_analyzer_result = analyze_saju_by_saju_analyzer(
        pillars['year'], pillars['month'], pillars['day'], pillars['hour']
    )

    # 추가: 三命通会 원문 해석 가져오기
    print("🔎 section_key:", normalize_section_key(pillars["day"], pillars["hour"]))
    ctext_rows = get_ctext_match(pillars["day"], pillars["hour"])
    ctext_explanation = None
    ctext_kr_literal = None
    if ctext_rows:
        ctext_explanation = "\n\n".join([row["content"] for row in ctext_rows])
        ctext_kr_literal = "\n\n".join([row["kr_literal"] for row in ctext_rows if row["kr_literal"]])

    return render_template(
        "page2.html",
        name=name,
        # today_fortune=today_fortune,
        # saju_analysis=saju_analysis,
        coffee_link=BUY_ME_A_COFFEE_LINK,
        ilju=ilju,
        ilju_interpretation=ilju_interpretation,
        saju_info=saju_info,
        get_twelve_gods_by_day_branch=get_twelve_gods_by_day_branch,
        saju_analyzer_result=saju_analyzer_result,
        ctext_explanation=ctext_explanation,
        ctext_kr_literal=ctext_kr_literal,
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

@app.route("/api/saju_ai_analysis", methods=["POST"])
def api_saju_ai_analysis():
    if "session_token" not in session:
        return {"error": "unauthorized"}, 401

    birthdate_str = session.get("birthdate")
    birth_hour = int(session.get("birthhour", 12))

    try:
        birthdate = datetime.strptime(birthdate_str, "%Y-%m-%d")
    except:
        return {"error": "invalid birthdate"}, 400

    pillars = calculate_four_pillars(datetime(birthdate.year, birthdate.month, birthdate.day, birth_hour))
    saju_info = get_saju_details(pillars)

    # 원문 해석과 일주 해석 병합
    ilju = pillars["day"]
    ilju_interpretation = get_ilju_interpretation(ilju)
    ilju_kr = ilju_interpretation.get("kr", "")

    # 삼명통회
    ctext = get_ctext_match(pillars["day"], pillars["hour"]) or ""

    # 오행/십성 분석
    saju_analyzer_result = analyze_saju_by_saju_analyzer(
        pillars['year'], pillars['month'], pillars['day'], pillars['hour']
    )

    # GPT에게 전달할 통합 프롬프트 구성
    prompt = f"""
당신은 사주 해석 전문가입니다.
다음은 한 사람의 사주 정보입니다:

- 일주: {ilju}
- 일주 해석 (DB): {ilju_kr}
- 삼명통회 원문: {ctext}
- 오행/십성 해석: {saju_analyzer_result}

이 정보를 종합하여, 이 사람의 인생 전반적 특성과 강점, 유의사항을 300자 내외로 종합 해석해주세요.
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "당신은 전문 사주 해석가입니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=600
        )
        reply = format_fortune_text(response.choices[0].message.content)
        return {"result": reply}
    except Exception as e:
        return {"error": str(e)}, 500

if __name__ == "__main__":
    app.run(debug=True)