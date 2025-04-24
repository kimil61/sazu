# four_pillars.py
from datetime import datetime
import sxtwl

# GAN = "갑을병정무기경신임계"   # 天干 0~9
# ZHI = "자축인묘진사오미신유술해" # 地支 0~11

GAN = "甲乙丙丁戊己庚辛壬癸"   # 天干 0~9
ZHI = "子丑寅卯辰巳午未申酉戌亥" # 地支 0~11


def four_pillars(dt: datetime) -> dict:
    """
    dt : 출생 시각(현지시간)
    """
    # sxtwl의 일자 객체 생성
    day = sxtwl.fromSolar(dt.year, dt.month, dt.day)

    # 각 기둥의 간지 구하기
    y_gz = day.getYearGZ(False)  # 입춘 경계 미적용
    m_gz = day.getMonthGZ()
    d_gz = day.getDayGZ()
    h_gz = day.getHourGZ(dt.hour)

    return {
        "year": GAN[y_gz.tg] + ZHI[y_gz.dz],
        "month": GAN[m_gz.tg] + ZHI[m_gz.dz],
        "day": GAN[d_gz.tg] + ZHI[d_gz.dz],
        "hour": GAN[h_gz.tg] + ZHI[h_gz.dz],
    }

if __name__ == "__main__":
    # 예시: 1984‑06‑01 08:30 (KST) → 갑자·기사·병인·무술
    dt = datetime(1984, 6, 1, 20, 21)
    print(four_pillars(dt))