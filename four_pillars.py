# four_pillars.py
from datetime import datetime, timedelta
import sxtwl

# GAN = "갑을병정무기경신임계"   # 天干 0~9
# ZHI = "자축인묘진사오미신유술해" # 地支 0~11

GAN = "甲乙丙丁戊己庚辛壬癸"   # 天干 0~9
ZHI = "子丑寅卯辰巳午未申酉戌亥" # 地支 0~11


def four_pillars_from_gmt(gmt_dt: datetime, tz_offset_hours: int = 9) -> dict:
    """
    gmt_dt : UTC 기준 datetime
    tz_offset_hours : 예: 한국은 +9
    """
    # UTC → 현지시간으로 변환
    local_dt = gmt_dt + timedelta(hours=tz_offset_hours)

    # 사주 계산
    day = sxtwl.fromSolar(local_dt.year, local_dt.month, local_dt.day)
    y_gz = day.getYearGZ(False)
    m_gz = day.getMonthGZ()
    d_gz = day.getDayGZ()
    h_gz = day.getHourGZ(local_dt.hour)

    return {
        "year": GAN[y_gz.tg] + ZHI[y_gz.dz],
        "month": GAN[m_gz.tg] + ZHI[m_gz.dz],
        "day": GAN[d_gz.tg] + ZHI[d_gz.dz],
        "hour": GAN[h_gz.tg] + ZHI[h_gz.dz],
    }

if __name__ == "__main__":
    # 예시: 1984‑06‑01 11:30 UTC → 한국시간 20:30 → 갑자·기사·병인·무술
    gmt_time = datetime(1984, 6, 1, 11, 30)
    print(four_pillars_from_gmt(gmt_time, tz_offset_hours=9))