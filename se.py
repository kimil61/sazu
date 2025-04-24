from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import sqlite3
import time

# 브라우저 설정
options = Options()
options.add_argument("--headless")
driver = webdriver.Chrome(options=options)
urls = [
    "https://ctext.org/wiki.pl?if=gb&chapter=330556&remap=gb",
    "https://ctext.org/wiki.pl?if=gb&chapter=805857&remap=gb"
]

all_html = []
for url in urls:
    driver.get(url)
    time.sleep(3)
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")
    all_html.append(soup)

driver.quit()

# DB 연결
conn = sqlite3.connect("ctext.db")
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS wiki_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section TEXT,
    line_number INTEGER,
    content TEXT
)
""")

for soup in all_html:
    all_rows = soup.select("tr.result")
    section_title = None
    line_number = 0

    for row in all_rows:
        h2 = row.find("h2")
        if h2:
            section_title = h2.get_text(strip=True).replace("《", "").replace("》", "")
            line_number = 0
            continue

        tds = row.find_all("td")
        if len(tds) == 2:
            content = tds[1].get_text(strip=True)
            if section_title and content:
                line_number += 1
                cur.execute("INSERT INTO wiki_content (section, line_number, content) VALUES (?, ?, ?)",
                            (section_title, line_number, content))

conn.commit()
conn.close()

print("모든 섹션 저장 완료!")