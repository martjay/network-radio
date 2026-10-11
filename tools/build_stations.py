"""Turn the verified probe results into the curated station database shipped
with the application.

Selection is evidence based: every station kept here was opened and decoded by
ffprobe. Ranking blends community votes, click counts, stream bitrate and
metadata completeness; per-genre and per-country caps keep the catalogue
balanced instead of drowning in one country's output.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "verified.json")
OUT = os.path.join(os.path.dirname(HERE), "assets", "stations.json")

MAX_TOTAL = 820
PER_GENRE = 64
PER_GENRE_HARD = 74
PER_COUNTRY = 44

# Regions guaranteed a floor in the catalogue regardless of global score, so a
# handful of high-vote Western stations can never crowd out the rest of the
# world. The app's interface is Chinese, so CN/HK/TW are weighted first.
PRIORITY_REGIONS: list[tuple[str, int]] = [
    ("CN", 40), ("HK", 22), ("TW", 26),
    ("US", 34), ("GB", 30), ("DE", 28), ("FR", 26), ("JP", 24), ("KR", 16),
    ("IT", 22), ("ES", 20), ("NL", 20), ("CA", 18), ("AU", 18), ("BR", 16),
    ("RU", 18), ("IN", 16), ("SG", 10), ("CH", 14), ("AT", 12), ("SE", 12),
    ("PL", 14), ("MX", 12), ("AR", 12), ("ZA", 10), ("TR", 10), ("PT", 12),
]

# --------------------------------------------------------------------------- #
#  Genre taxonomy -- first bucket whose keywords hit the strongest wins.
#  (key, display zh, display en, keyword list)
# --------------------------------------------------------------------------- #
GENRES: list[tuple[str, str, str, list[str]]] = [
    ("news", "新闻资讯", "NEWS & TALK", [
        "news", "talk", "information", "info", "aktuell", "nachrichten", "noticias",
        "notizie", "nouvelles", "nyheter", "actualidad", "radio nacional", "public radio",
        "world service", "bbc world", "deutschlandfunk", "npr", "talkradio", "radio 1 news",
        "新闻", "资讯", "财经", "经济", "交通", "之声", "时报", "评论",
    ]),
    ("classical", "古典音乐", "CLASSICAL", [
        "classical", "classic fm", "klassik", "clasica", "classique", "opera", "symphony",
        "philharmonic", "orchestra", "chamber", "baroque", "concerto", "wclv", "venice classic",
        "radio classica", "beethoven", "mozart", "bach",
        "古典", "交响", "音乐厅", "歌剧", "爱乐",
    ]),
    ("jazz", "爵士蓝调", "JAZZ & BLUES", [
        "jazz", "smooth jazz", "swing", "bebop", "bossa", "big band", "blues", "ragtime",
        "jazz24", "cool jazz", "soul jazz", "venice jazz",
        "爵士", "蓝调", "布鲁斯",
    ]),
    ("electronic", "电子舞曲", "ELECTRONIC", [
        "electronic", "house", "techno", "trance", "edm", "dance", "electro", "drum and bass",
        "dnb", "dubstep", "hardstyle", "rave", "club", "nightclub", "psytrance", "hardcore",
        "minimal", "deep house", "ibiza", "gabber", "happy hardcore",
        "电子", "电音", "舞曲", "慢摇", "迪厅",
    ]),
    ("chill", "氛围休闲", "AMBIENT & CHILL", [
        "ambient", "lounge", "chillout", "chill out", "chill", "downtempo", "easy listening",
        "relax", "sleep", "meditation", "zen", "spa", "calm", "new age", "drone", "space music",
        "lofi", "lo-fi",
        "轻音乐", "休闲", "氛围", "放松", "助眠", "治愈",
    ]),
    ("rock", "摇滚金属", "ROCK & METAL", [
        "rock", "metal", "punk", "alternative", "grunge", "hardcore rock", "classic rock",
        "indie rock", "heavy metal", "thrash", "gothic", "emo", "post rock", "prog",
        "摇滚", "金属", "朋克",
    ]),
    ("pop", "流行金曲", "POP & HITS", [
        "pop", "hits", "top 40", "top40", "chart", "hit radio", "hitradio", "contemporary",
        "mainstream", "hot mix", "power hit", "music fm", "hit fm", "kiss fm", "energy",
        "流行", "金曲", "音乐台", "音乐广播", "音乐之声", "热歌", "榜单",
    ]),
    ("urban", "嘻哈节奏", "HIP-HOP & R&B", [
        "hip hop", "hiphop", "hip-hop", "rap", "rnb", "r&b", "urban", "soul", "funk", "groove",
        "motown", "disco", "boogie", "trap",
        "嘻哈", "说唱", "节奏布鲁斯",
    ]),
    ("folk", "民谣乡村", "FOLK & COUNTRY", [
        "folk", "country", "acoustic", "americana", "bluegrass", "singer songwriter", "celtic",
        "irish", "guitar", "world music folk",
        "民谣", "民歌", "乡村", "原声吉他",
    ]),
    ("world", "世界拉丁", "WORLD & LATIN", [
        "latin", "salsa", "reggaeton", "world", "reggae", "afro", "african", "caribbean", "ska",
        "bollywood", "hindi", "arabic", "turkish", "greek", "flamenco", "tango", "cumbia",
        "bachata", "kizomba", "asian", "k-pop", "kpop", "j-pop", "jpop", "anime",
        "民族", "戏曲", "粤剧", "京剧", "山歌", "世界音乐", "国乐", "古风",
    ]),
    ("oldies", "怀旧年代", "OLDIES & RETRO", [
        "oldies", "80s", "90s", "70s", "60s", "retro", "vintage", "nostalgia", "classic hits",
        "gold", "schlager", "evergreen", "memory", "oldie", "50s",
        "怀旧", "老歌", "经典老", "年代", "回忆",
    ]),
    ("screen", "影视原声", "SCREEN & SCORE", [
        "soundtrack", "score", "film", "cinema", "movie", "ost", "game music", "video game",
        "anime music", "kino", "musical", "broadway",
        "影视", "电影", "原声", "动漫",
    ]),
    ("sport", "体育赛事", "SPORT", [
        "sport", "sports", "football", "soccer", "cricket", "nba", "espn", "deportes", "sportif",
        "racing", "f1",
        "体育", "赛事", "足球", "篮球",
    ]),
    ("culture", "文化谈话", "CULTURE & SPOKEN", [
        "culture", "education", "spoken", "audiobook", "book", "history", "science", "comedy",
        "story", "drama", "radio drama", "podcast", "interview", "art", "theatre", "theater",
        "philosophy", "language",
        "文化", "故事", "评书", "相声", "小说", "教育", "谈话", "讲堂", "戏曲故事",
    ]),
]

# extra credit keywords -> genre key
STRONG = {
    "news": ["bbc world service", "deutschlandfunk", "npr news", "radio nacional"],
    "classical": ["classic fm", "venice classic", "radio classica"],
    "jazz": ["jazz24", "venice jazz", "smooth jazz"],
    "electronic": ["techno", "trance", "house music"],
    "rock": ["classic rock", "metal"],
}

COUNTRY_ZH = {
    "CN": "中国", "HK": "中国香港", "TW": "中国台湾", "MO": "中国澳门",
    "US": "美国", "GB": "英国", "DE": "德国", "FR": "法国", "JP": "日本",
    "KR": "韩国", "IT": "意大利", "ES": "西班牙", "NL": "荷兰", "CH": "瑞士",
    "AT": "奥地利", "CA": "加拿大", "AU": "澳大利亚", "BR": "巴西", "RU": "俄罗斯",
    "PL": "波兰", "SE": "瑞典", "NO": "挪威", "DK": "丹麦", "FI": "芬兰",
    "IE": "爱尔兰", "BE": "比利时", "PT": "葡萄牙", "GR": "希腊", "TR": "土耳其",
    "IN": "印度", "SG": "新加坡", "MY": "马来西亚", "TH": "泰国", "ID": "印度尼西亚",
    "PH": "菲律宾", "VN": "越南", "MX": "墨西哥", "AR": "阿根廷", "CL": "智利",
    "CO": "哥伦比亚", "PE": "秘鲁", "ZA": "南非", "EG": "埃及", "MA": "摩洛哥",
    "NG": "尼日利亚", "KE": "肯尼亚", "AE": "阿联酋", "SA": "沙特阿拉伯", "IL": "以色列",
    "CZ": "捷克", "HU": "匈牙利", "RO": "罗马尼亚", "UA": "乌克兰", "BG": "保加利亚",
    "HR": "克罗地亚", "RS": "塞尔维亚", "SK": "斯洛伐克", "SI": "斯洛文尼亚",
    "LT": "立陶宛", "LV": "拉脱维亚", "EE": "爱沙尼亚", "IS": "冰岛", "NZ": "新西兰",
    "IE2": "爱尔兰", "LU": "卢森堡", "MT": "马耳他", "CY": "塞浦路斯", "PK": "巴基斯坦",
    "BD": "孟加拉国", "LK": "斯里兰卡", "NP": "尼泊尔", "IR": "伊朗", "IQ": "伊拉克",
    "JO": "约旦", "LB": "黎巴嫩", "KW": "科威特", "QA": "卡塔尔", "OM": "阿曼",
    "BH": "巴林", "TN": "突尼斯", "DZ": "阿尔及利亚", "GH": "加纳", "TZ": "坦桑尼亚",
    "UG": "乌干达", "ZW": "津巴布韦", "CU": "古巴", "DO": "多米尼加", "GT": "危地马拉",
    "EC": "厄瓜多尔", "BO": "玻利维亚", "PY": "巴拉圭", "UY": "乌拉圭", "VE": "委内瑞拉",
    "CR": "哥斯达黎加", "PA": "巴拿马", "HN": "洪都拉斯", "SV": "萨尔瓦多",
    "PR": "波多黎各", "MD": "摩尔多瓦", "BY": "白俄罗斯", "GE": "格鲁吉亚", "AM": "亚美尼亚",
    "AZ": "阿塞拜疆", "KZ": "哈萨克斯坦", "UZ": "乌兹别克斯坦", "MN": "蒙古",
    "KH": "柬埔寨", "LA": "老挝", "MM": "缅甸", "BN": "文莱", "FJ": "斐济",
}

CHINESE_MARKERS = ("chinese", "mandarin", "cantonese", "中文", "华语", "国语", "粤语", "台灣", "台湾", "香港")

CJK = re.compile(r"[\u4e00-\u9fff]")
BAD_NAME = re.compile(
    r"(test|do not|dummy|placeholder|^\s*$|https?://|\.mp3$|\.pls$|\.m3u$|"
    r"unknown|unnamed|no name|stream\s*\d*$|radio\s*$)",
    re.I,
)


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", s).strip()


def clean_name(name: str) -> str:
    n = norm_text(name)
    n = re.sub(r"^[\-\|\*\s]+|[\-\|\*\s]+$", "", n)
    n = re.sub(r"\s*[\(\[]\s*(?:www\.)?[\w\.\-]+\.(?:com|net|org|de|fr|it|es|nl|ru|cn|jp|fm|info|radio)[^\]]*[\)\]]\s*$", "", n, flags=re.I)
    n = re.sub(r"\s{2,}", " ", n)
    return n.strip()[:64] or norm_text(name)[:64]


def classify(rec: dict) -> str:
    hay = " ".join([
        rec.get("name", ""), rec.get("tags", ""), rec.get("icy_genre", ""),
    ]).lower()
    hay = hay.replace("_", " ").replace("/", " ").replace(",", " ")
    if not hay.strip():
        return "varied"

    scores: dict[str, float] = {}
    for key, _zh, _en, kws in GENRES:
        sc = 0.0
        for kw in kws:
            if kw in hay:
                # word-boundary-ish weight: longer keywords are more specific
                sc += 1.0 + min(len(kw), 14) / 14.0
        for kw in STRONG.get(key, []):
            if kw in hay:
                sc += 3.0
        if sc:
            scores[key] = sc
    if not scores:
        return "varied"
    return max(scores.items(), key=lambda kv: kv[1])[0]


def is_chinese(rec: dict) -> bool:
    if rec.get("countrycode") in ("CN", "TW", "HK", "MO"):
        return True
    hay = (rec.get("language", "") + " " + rec.get("tags", "") + " " + rec.get("name", "")).lower()
    return any(m in hay for m in CHINESE_MARKERS) or bool(CJK.search(rec.get("name", "")))


def score_of(rec: dict) -> float:
    br = rec.get("bitrate") or 0
    sc = 0.0
    sc += min(rec.get("votes", 0), 400) * 0.85
    sc += min(rec.get("clicks", 0), 4000) * 0.10
    sc += min(br, 320) * 0.45
    if rec.get("homepage"):
        sc += 6
    if rec.get("favicon"):
        sc += 3
    if rec.get("icy_name"):
        sc += 4
    if (rec.get("real_codec") or "") in ("mp3", "aac"):
        sc += 6
    if rec.get("channels") == 2:
        sc += 4
    if is_chinese(rec):
        sc += 5
    if CJK.search(rec.get("name", "")):
        sc += 6
    return sc


def main() -> None:
    with open(SRC, encoding="utf-8") as fh:
        raw = json.load(fh)

    live = [r for r in raw if r.get("ok")]
    print(f"live streams: {len(live)}")

    # ---- clean + dedupe ---------------------------------------------------
    seen_url: set[str] = set()
    seen_nc: set[str] = set()
    pool: list[dict] = []
    for r in live:
        name = clean_name(r.get("name", ""))
        if not name or BAD_NAME.search(name):
            continue
        url = r["url"].strip()
        uk = url.rstrip("/").lower()
        if uk in seen_url:
            continue
        cc = (r.get("countrycode") or "").upper()
        nk = (re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", name.lower())[:28], cc)
        if nk in seen_nc:
            continue
        seen_url.add(uk)
        seen_nc.add(nk)

        genre = classify(r)
        rec = {
            "name": name,
            "url": url,
            "genre": genre,
            "country": COUNTRY_ZH.get(cc) or norm_text(r.get("country") or "") or "其他",
            "cc": cc,
            "region": {"CN": "cn", "HK": "hk", "TW": "tw", "MO": "mo"}.get(cc, ""),
            "state": norm_text(r.get("state") or ""),
            "language": norm_text(r.get("language") or ""),
            "tags": norm_text(r.get("tags") or ""),
            "homepage": (r.get("homepage") or "").strip(),
            "favicon": (r.get("favicon") or "").strip(),
            "codec": (r.get("real_codec") or "").upper(),
            "bitrate": int(r.get("bitrate") or 0),
            "sample_rate": r.get("sample_rate") or "",
            "channels": int(r.get("channels") or 0),
            "votes": int(r.get("votes") or 0),
            "clicks": int(r.get("clicks") or 0),
            "zh": is_chinese(r),
            "score": round(score_of(r), 2),
        }
        pool.append(rec)

    print(f"after cleaning/dedupe: {len(pool)}")
    pool.sort(key=lambda r: -r["score"])

    # ---- selection --------------------------------------------------------
    # Three passes, in priority order:
    #   1. regional floor  - every priority region gets its quota first
    #   2. genre balance   - fill each genre up to its soft cap
    #   3. genre top-up    - relax the country cap to reach the total
    chosen: list[dict] = []
    picked: set[str] = set()
    per_genre: dict[str, int] = {}
    per_cc: dict[str, int] = {}

    def take(rec: dict) -> None:
        picked.add(rec["url"])
        g = rec["genre"]
        cc = rec["cc"] or "??"
        per_genre[g] = per_genre.get(g, 0) + 1
        per_cc[cc] = per_cc.get(cc, 0) + 1
        chosen.append(rec)

    # -- pass 1: regional floors -------------------------------------------
    for cc, quota in PRIORITY_REGIONS:
        rows = [r for r in pool if (r["cc"] or "??") == cc and r["url"] not in picked]
        got = 0
        for rec in rows:
            if got >= quota:
                break
            g = rec["genre"]
            if per_genre.get(g, 0) >= PER_GENRE_HARD:
                continue
            take(rec)
            got += 1

    # -- pass 2: genre balance ---------------------------------------------
    for rec in pool:
        if len(chosen) >= MAX_TOTAL:
            break
        if rec["url"] in picked:
            continue
        g = rec["genre"]
        cc = rec["cc"] or "??"
        if per_genre.get(g, 0) >= PER_GENRE:
            continue
        if per_cc.get(cc, 0) >= PER_COUNTRY:
            continue
        take(rec)

    # -- pass 3: top-up (country cap relaxed) ------------------------------
    for rec in pool:
        if len(chosen) >= MAX_TOTAL:
            break
        if rec["url"] in picked:
            continue
        g = rec["genre"]
        if per_genre.get(g, 0) >= PER_GENRE_HARD:
            continue
        take(rec)

    print(f"selected: {len(chosen)}")
    print("  per genre :", dict(sorted(per_genre.items(), key=lambda kv: -kv[1])))
    print("  per country:", dict(sorted(per_cc.items(), key=lambda kv: -kv[1])[:18]))

    # ---- country index ----------------------------------------------------
    countries: dict[str, int] = {}
    for r in chosen:
        countries[r["country"]] = countries.get(r["country"], 0) + 1

    genres_meta = [
        {"key": k, "zh": zh, "en": en, "count": per_genre.get(k, 0)}
        for k, zh, en, _ in GENRES
    ]
    genres_meta.append({"key": "varied", "zh": "综合电台", "en": "VARIED", "count": per_genre.get("varied", 0)})
    genres_meta = [g for g in genres_meta if g["count"] > 0]

    payload = {
        "generated": __import__("datetime").date.today().isoformat(),
        "source": "radio-browser.info (community database) - every stream verified with ffprobe",
        "total": len(chosen),
        "genres": genres_meta,
        "countries": sorted(
            [{"name": k, "count": v} for k, v in countries.items()],
            key=lambda d: -d["count"],
        ),
        "stations": sorted(chosen, key=lambda r: (r["genre"], -r["score"])),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, separators=(",", ": "))
    size = os.path.getsize(OUT) / 1024
    print(f"\nwrote {OUT}  ({size:.0f} KB, {len(chosen)} stations)")
    zh = sum(1 for r in chosen if r["zh"])
    print(f"chinese-language stations: {zh}")


if __name__ == "__main__":
    main()
