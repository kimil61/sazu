import os
import sqlite3
import openai
import time
from dotenv import load_dotenv
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# DB 연결
conn = sqlite3.connect("ctext.db")
cur = conn.cursor()

# 아직 번역되지 않은 행만 가져옴
cur.execute("SELECT id, content FROM wiki_content WHERE kr_literal IS NULL OR kr_explained IS NULL")
rows = cur.fetchall()

for row in rows:
    id_, content = row
    try:
        # 1. 직역 프롬프트 (고전적·운율적·우아한 톤)
        prompt_literal = f"""
《三命通会》에 실린 다음 문장을, 고전 한문 느낌을 살려 운율 있고 우아하게 한국어로 직역해 주세요.
문장이 마치 조선시대 운명서의 구절처럼 고풍스럽고 기품 있게 들리도록 해주세요.
한자어를 살리고, 필요한 경우 괄호로 의미를 덧붙여도 됩니다.

중국어 원문: {content}
"""

        # 2. 해설 프롬프트 (현대적·직관적·임팩트 있는 톤)
        prompt_explained = f"""
다음은 중국 명리 고전 《三命通会》에 나오는 문장입니다.

이 문장을 현대 한국인이 "직관적으로 바로 이해"할 수 있도록 풀어주세요.
말하듯 자연스럽게, 감정도 담아서 써주세요. 문장이 따분하지 않고 흥미롭게 느껴지도록!
재물운이면 "돈 들어온다", 연애면 "사랑 꽃핀다"처럼 핵심을 강조해서 표현해 주세요.

중국어 원문: {content}
"""

        # GPT 호출
        literal_resp = openai.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt_literal}],
            temperature=0.4
        )

        explained_resp = openai.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt_explained}],
            temperature=0.6
        )

        kr_literal = literal_resp.choices[0].message.content.strip()
        kr_explained = explained_resp.choices[0].message.content.strip()

        # DB 업데이트
        cur.execute("""
            UPDATE wiki_content
            SET kr_literal = ?, kr_explained = ?
            WHERE id = ?
        """, (kr_literal, kr_explained, id_))

        conn.commit()
        print(f"[{id_}] 번역 완료")
        time.sleep(1.5)  # Rate limit 방지

    except Exception as e:
        print(f"[{id_}] 오류 발생: {e}")
        continue

conn.close()