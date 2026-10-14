"""Genre taxonomy, scoring and balanced selection.

Used both when shipping `assets/stations.json` and when the running app
syncs against radio-browser.info, so a station is classified the same way
in the installer and after a later catalogue update.
"""
from __future__ import annotations

import re
import unicodedata

from .geo import COUNTRY_ZH, country_zh, language_zh  # noqa: F401

# Snapshot baked into the installer. Live sync may grow past this, but the
# shipped file stays a verified, balanced core.
SHIP_MAX = 820
SHIP_PER_GENRE = 64
SHIP_PER_GENRE_HARD = 74
SHIP_PER_COUNTRY = 44

# In-app sync: 0 means no cap. Regional floors still run first so CN/HK/TW
# are not buried, then every remaining live station can be added.
LIVE_MAX = 0
LIVE_PER_GENRE = 0
LIVE_PER_GENRE_HARD = 0
LIVE_PER_COUNTRY = 0

SHIP_PRIORITY: list[tuple[str, int]] = [
    ("CN", 40), ("HK", 22), ("TW", 26),
    ("US", 34), ("GB", 30), ("DE", 28), ("FR", 26), ("JP", 24), ("KR", 16),
    ("IT", 22), ("ES", 20), ("NL", 20), ("CA", 18), ("AU", 18), ("BR", 16),
    ("RU", 18), ("IN", 16), ("SG", 10), ("CH", 14), ("AT", 12), ("SE", 12),
    ("PL", 14), ("MX", 12), ("AR", 12), ("ZA", 10), ("TR", 10), ("PT", 12),
]

LIVE_PRIORITY: list[tuple[str, int]] = [
    ("CN", 72), ("HK", 36), ("TW", 48),
    ("US", 80), ("GB", 64), ("DE", 64), ("FR", 56), ("JP", 48), ("KR", 28),
    ("IT", 44), ("ES", 40), ("NL", 40), ("CA", 36), ("AU", 32), ("BR", 32),
    ("RU", 36), ("IN", 32), ("SG", 18), ("CH", 24), ("AT", 20), ("SE", 22),
    ("PL", 28), ("MX", 24), ("AR", 22), ("ZA", 18), ("TR", 20), ("PT", 22),
]

# (key, display zh, display en, keyword list)
GENRES: list[tuple[str, str, str, list[str]]] = [
    ("news", "新闻资讯", "NEWS", [
        "news", "information", "aktuell", "nachrichten", "noticias",
        "notizie", "nouvelles", "nyheter", "actualidad", "radio nacional", "public radio",
        "world service", "bbc world", "deutschlandfunk", "npr", "radio 1 news", "local news",
        "france info", "france inter", "radio farda", "rfi",
        "radio france internationale", "deutsche welle", "al jazeera",
        "voice of america", "sky news", "fox news", "cnn", "msnbc",
        "iran international", "radio nationale", "france bleu",
        "新闻", "资讯", "财经", "经济", "交通", "之声", "时报", "评论",
    ]),
    ("talk", "谈话访谈", "TALK", [
        "talk", "talkradio", "talk radio", "news talk", "spoken", "interview",
        "radio hablada", "call in", "call-in", "spoken word", "谈话", "访谈", "夜话",
    ]),
    ("classical", "古典音乐", "CLASSICAL", [
        "classical", "classic fm", "klassik", "clasica", "classique", "opera", "symphony",
        "philharmonic", "orchestra", "chamber", "baroque", "concerto", "wclv", "venice classic",
        "radio classica", "beethoven", "mozart", "bach",
        "filharmonia", "filharmonie", "philharmonie", "klassiek",
        "古典", "交响", "音乐厅", "歌剧", "爱乐",
    ]),
    ("jazz", "爵士", "JAZZ", [
        "jazz", "smooth jazz", "swing", "bebop", "bossa", "big band", "ragtime",
        "jazz24", "cool jazz", "soul jazz", "venice jazz", "vocal jazz",
        "爵士",
    ]),
    ("blues", "蓝调", "BLUES", [
        "blues", "delta blues", "chicago blues", "blues rock", "rhythm and blues",
        "蓝调", "布鲁斯",
    ]),
    ("electronic", "电子舞曲", "ELECTRONIC", [
        "electronic", "house", "techno", "trance", "edm", "dance", "electro", "drum and bass",
        "dnb", "dubstep", "hardstyle", "rave", "club", "nightclub", "psytrance", "hardcore",
        "minimal", "deep house", "ibiza", "gabber", "happy hardcore",
        "eurodance", "italo dance", "dancefloor", "tech house",
        "drum n bass", "drum bass",
        "电子", "电音", "舞曲", "慢摇", "迪厅",
    ]),
    ("chill", "氛围休闲", "AMBIENT & CHILL", [
        "ambient", "lounge", "chillout", "chill out", "chill", "downtempo", "easy listening",
        "relax", "sleep", "meditation", "zen", "spa", "calm", "new age", "drone", "space music",
        "lofi", "lo-fi", "instrumental", "buddha",
        "轻音乐", "休闲", "氛围", "放松", "助眠", "治愈",
    ]),
    ("rock", "摇滚", "ROCK", [
        "rock", "punk", "alternative", "grunge", "hardcore rock", "classic rock",
        "indie rock", "emo", "post rock", "prog", "pop rock", "soft rock", "hard rock",
        "hardrock", "rock n roll", "rock and roll", "rockabilly",
        "rockantenne", "indie",
        "摇滚", "朋克", "roks",
    ]),
    ("metal", "金属", "METAL", [
        "metal", "heavy metal", "death metal", "black metal", "thrash", "doom",
        "power metal", "nu metal", "metalcore", "gothic metal", "hardcore metal",
        "金属",
    ]),
    ("pop", "流行金曲", "POP & HITS", [
        "pop", "hits", "hit", "top 40", "top40", "top 50", "hot 100", "chart",
        "hit radio", "hitradio", "contemporary", "mainstream", "hot mix", "power hit",
        "music fm", "hit fm", "kiss fm", "energy", "nrj", "cherie", "exitos",
        "love songs", "adult contemporary", "hitmix", "rfm", "европа плюс", "europa plus",
        "cadena 100", "cadena dial", "los 40", "los40", "virgin radio",
        "fun radio", "radio 538", "q-music", "qmusic", "greatest hits",
        "bbc radio 1", "bbc radio 2", "авторадио", "русское радио",
        "sky radio", "hitsonly", "top hits", "top 10", "top 20",
        "hitz", "kiss radio", "kiss kiss", "love radio", "love fm",
        "musica italiana",
        "流行", "金曲", "音乐台", "音乐广播", "音乐之声", "热歌", "榜单",
    ]),
    ("urban", "嘻哈节奏", "HIP-HOP & R&B", [
        "hip hop", "hiphop", "hip-hop", "rap", "rnb", "r&b", "urban", "soul", "funk", "groove",
        "motown", "disco", "boogie", "trap", "raproyal",
        "嘻哈", "说唱", "节奏布鲁斯",
    ]),
    ("folk", "民谣", "FOLK", [
        "folk", "acoustic", "singer songwriter", "celtic", "irish",
        "guitar", "world music folk", "民谣", "民歌", "原声吉他",
    ]),
    ("country", "乡村", "COUNTRY", [
        "country", "americana", "bluegrass", "classic country", "country music",
        "乡村",
    ]),
    ("world", "世界音乐", "WORLD", [
        "world", "reggae", "afro", "african", "caribbean", "ska",
        "bollywood", "bolly", "hindi", "arabic", "turkish", "greek",
        "asian", "k-pop", "kpop", "j-pop", "jpop", "anime",
        "arabesk", "dangdut", "tarab", "punjabi", "bhangra", "tamil", "nepali",
        "manele", "laika", "fado", "highlife", "afrobeat", "rai music",
        "campursari", "keroncong", "gamelan", "soukous", "zouk",
        "mandopop", "cantopop", "enka", "persian", "farsi", "kurdish",
        "malayalam", "telugu", "kannada", "marathi", "bengali", "bangla",
        "pinoy", "opm", "campur sari", "maghreb", "damar",
        "africa", "narodni", "lautar", "only rai", "slovenian", "croatian",
        "portuguese music", "ex-yu", "nepal", "turk fm", "indigenous",
        "民族", "戏曲", "粤剧", "京剧", "山歌", "世界音乐", "国乐", "古风",
    ]),
    ("latin", "拉丁美洲", "LATIN", [
        "latin", "salsa", "reggaeton", "flamenco", "tango", "cumbia",
        "bachata", "kizomba", "merengue", "latino", "vallenato", "ranchera", "mariachi",
        "regional mexican", "regional mexicana", "grupera", "norteño", "banda",
        "música mexicana", "musica mexicana", "música en español",
        "latin pop", "latin jazz", "sertanejo", "forro", "pagode", "samba", "mpb",
        "tropical", "romantica", "tejano", "norteno", "sierreno", "balada",
        "mexican music",
    ]),
    ("oldies", "怀旧年代", "OLDIES & RETRO", [
        "oldies", "80s", "90s", "70s", "60s", "50s", "80er", "90er", "70er", "60er",
        "eighties", "nineties", "seventies", "sixties", "flashback", "golden",
        "retro", "vintage", "nostalgia", "classic hits", "gold", "schlager",
        "evergreen", "memory", "oldie", "anos 80", "anos 90", "anos 70",
        "golden hits", "gold radio", "classics", "christmas",
        "nostalgie", "nostalgija", "nostalji", "chanson",
        "怀旧", "老歌", "经典老", "年代", "回忆",
    ]),
    ("screen", "影视原声", "SCREEN & SCORE", [
        "soundtrack", "score", "film", "cinema", "movie", "ost", "game music", "video game",
        "anime music", "kino", "musical", "broadway", "disney",
        "影视", "电影", "原声", "动漫",
    ]),
    ("sport", "体育赛事", "SPORT", [
        "sport", "sports", "football", "soccer", "cricket", "nba", "espn", "deportes", "sportif",
        "racing", "f1",
        "体育", "赛事", "足球", "篮球",
    ]),
    ("culture", "文化教育", "CULTURE", [
        "culture", "education", "audiobook", "book", "history", "science", "comedy",
        "story", "drama", "radio drama", "podcast", "art", "theatre", "theater",
        "philosophy", "language", "educational", "humor", "humour", "kids", "children",
        "audiobooks", "literatura", "cultural programming",
        "文化", "故事", "评书", "相声", "小说", "教育", "讲堂", "戏曲故事",
    ]),
    ("faith", "宗教福音", "FAITH", [
        "christian", "gospel", "worship", "catholic", "religious", "religion",
        "bible", "cristiana", "church", "islamic", "quran", "koran", "hindu",
        "kristen", "rohani", "mantra", "praise", "islam", "muslim",
        "buddhist", "orthodox", "iglesia", "evangelica", "adventist",
        "religiao", "religião",
        "福音", "基督教", "宗教", "古兰", "清真", "قرآن", "القرآن",
    ]),
]

STRONG = {
    "news": ["bbc world service", "deutschlandfunk", "npr news", "radio nacional", "france info", "al jazeera"],
    "talk": ["news talk", "talk radio", "talkradio"],
    "classical": ["classic fm", "venice classic", "radio classica"],
    "jazz": ["jazz24", "venice jazz", "smooth jazz"],
    "blues": ["chicago blues", "delta blues"],
    "electronic": ["techno", "trance", "house music"],
    "rock": ["classic rock", "indie rock"],
    "metal": ["heavy metal", "death metal", "black metal"],
    "pop": ["nrj", "hit fm", "top 40", "europa plus", "los 40", "cadena 100"],
    "oldies": ["classic hits", "flashback", "80er", "90er", "nostalgie"],
    "country": ["classic country", "country music"],
    "latin": ["regional mexican", "regional mexicana", "latin pop", "sertanejo", "vallenato"],
    "faith": ["christian radio", "gospel music", "quran"],
}

CHINESE_MARKERS = ("chinese", "mandarin", "cantonese", "中文", "华语", "国语", "粤语", "台灣", "台湾", "香港")
CJK = re.compile(r"[\u4e00-\u9fff]")
BAD_NAME = re.compile(
    r"(test|do not|dummy|placeholder|^\s*$|https?://|\.mp3$|\.pls$|\.m3u$|"
    r"unknown|unnamed|no name|stream\s*\d*$|radio\s*$)",
    re.I,
)
STATION_FIELDS = (
    "name", "url", "genre", "country", "cc", "region", "state", "language",
    "tags", "homepage", "favicon", "codec", "bitrate", "sample_rate",
    "channels", "votes", "clicks", "zh", "score",
)


def norm_text(s: str) -> str:
    text = unicodedata.normalize("NFKD", s or "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", text).strip()


def fold_match_text(s: str) -> str:
    """Lowercase haystack for keyword matching: strip accents, unify separators."""
    text = unicodedata.normalize("NFKD", s or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.lower().replace("_", " ").replace("/", " ").replace("&", " ")
    text = text.replace("-", " ").replace(",", " ").replace(";", " ")
    text = text.replace("#", " ").replace("+", " ")
    return re.sub(r"\s+", " ", text).strip()


def _compile_kw(kw: str):
    kw = fold_match_text(kw)
    if not kw:
        return None
    nlen = len(kw)
    # Short tokens: allow `rockfm` / `hitsonly` / `jazz24`, but not `film` in `filharmonia`.
    if " " not in kw and nlen <= 4:
        glued = r"(?:fm|radio|only|mix|music|[0-9]+)?"
        return (
            "re",
            re.compile(r"(?<![a-z])" + re.escape(kw) + glued + r"(?![a-z]{3,})"),
            nlen,
        )
    return ("sub", kw, nlen)


def keyword_in(kw: str, hay: str) -> bool:
    spec = _compile_kw(kw)
    if not spec or not hay:
        return False
    return _spec_hits(spec, hay)


def _spec_hits(spec, hay: str) -> bool:
    kind, val, _nlen = spec
    if kind == "sub":
        return val in hay
    return val.search(hay) is not None


_GENRE_MATCHERS: list[tuple[str, list, list]] = []
for _key, _zh, _en, _kws in GENRES:
    _GENRE_MATCHERS.append((
        _key,
        [s for s in (_compile_kw(k) for k in _kws) if s],
        [s for s in (_compile_kw(k) for k in STRONG.get(_key, [])) if s],
    ))


# `superhits` / `synthpop` / `hardrock` where the genre sits at the end of a compound.
_COMPOUND_TAILS: list[tuple[str, re.Pattern]] = [
    (key, re.compile(r"[a-z]{3,8}" + stem + r"(?![a-z0-9])"))
    for key, stem in (
        ("pop", "hits"), ("pop", "hit"), ("pop", "pop"),
        ("rock", "rock"), ("jazz", "jazz"), ("news", "news"),
        ("electronic", "dance"), ("electronic", "house"),
        ("metal", "metal"), ("blues", "blues"), ("folk", "folk"),
        ("rock", "punk"), ("urban", "soul"), ("urban", "funk"),
        ("urban", "rap"), ("talk", "talk"), ("chill", "chill"),
        ("oldies", "gold"), ("sport", "sport"),
    )
]


# Untagged local FMs: country is a better signal than stuffing them into 流行.
_CC_LATIN = frozenset({
    "MX", "GT", "HN", "SV", "NI", "CR", "PA", "CU", "DO", "PR", "HT",
    "CO", "VE", "EC", "PE", "BO", "PY", "UY", "CL", "AR", "BR",
})
_CC_WORLD = frozenset({
    "IN", "PK", "BD", "NP", "LK", "ID", "MY", "TH", "VN", "KH", "LA", "MM", "PH",
    "TR", "IR", "IQ", "SA", "AE", "EG", "MA", "DZ", "TN", "LY", "YE", "JO", "LB",
    "SY", "SD", "PS", "KW", "QA", "OM", "BH",
    "NG", "KE", "GH", "ET", "TZ", "UG", "SN", "CI", "CM", "ZA",
    "GR", "RS", "BA", "ME", "MK", "AL", "XK", "AM", "GE", "AZ", "UZ", "KZ",
})
_LANG_WORLD = (
    "阿拉伯语", "印地语", "泰米尔语", "土耳其语", "波斯语", "希腊语", "尼泊尔语",
    "泰语", "越南语", "印尼语", "马来语", "孟加拉语", "旁遮普语", "乌尔都语",
    "arabic", "hindi", "tamil", "turkish", "persian", "farsi", "greek", "nepali",
    "thai", "vietnamese", "indonesian", "malay", "bengali", "punjabi", "urdu",
)
_LANG_LATIN = (
    "西班牙语", "葡萄牙语", "spanish", "espanol", "portuguese", "brazilian",
)


def _fallback_genre(rec: dict) -> str:
    cc = (rec.get("countrycode") or rec.get("cc") or "").upper()
    if cc in _CC_LATIN:
        return "latin"
    if cc in _CC_WORLD:
        return "world"
    lang = fold_match_text(rec.get("language") or "")
    if cc in ("ES", "PT"):
        return "varied"
    if any(token in lang for token in _LANG_LATIN):
        return "latin"
    if any(token in lang for token in _LANG_WORLD):
        return "world"
    return "varied"


_OLDIES_DECADE = re.compile(
    r"(?<![0-9])(?:50|60|70|80|90)['’]?s(?![0-9])"
    r"|(?:50|60|70|80|90)er(?![a-z])"
    r"|de (?:50|60|70|80|90)(?:\s|$|-|a)"
)


def clean_name(name: str) -> str:
    n = norm_text(name)
    n = re.sub(r"^[\-\|\*\s]+|[\-\|\*\s]+$", "", n)
    n = re.sub(
        r"\s*[\(\[]\s*(?:www\.)?[\w\.\-]+\.(?:com|net|org|de|fr|it|es|nl|ru|cn|jp|fm|info|radio)"
        r"[^\]]*[\)\]]\s*$",
        "", n, flags=re.I,
    )
    n = re.sub(r"\s{2,}", " ", n)
    return n.strip()[:64] or norm_text(name)[:64]


def classify(rec: dict) -> str:
    hay = fold_match_text(" ".join([
        rec.get("name", ""), rec.get("tags", ""), rec.get("icy_genre", ""),
    ]))
    scores: dict[str, float] = {}
    if hay:
        for key, specs, strong_specs in _GENRE_MATCHERS:
            sc = 0.0
            for spec in specs:
                if _spec_hits(spec, hay):
                    sc += 1.0 + min(spec[2], 14) / 14.0
            for spec in strong_specs:
                if _spec_hits(spec, hay):
                    sc += 3.0
            if sc:
                scores[key] = sc
        for key, rx in _COMPOUND_TAILS:
            if rx.search(hay):
                scores[key] = scores.get(key, 0.0) + 1.5
        if _OLDIES_DECADE.search(hay):
            scores["oldies"] = scores.get("oldies", 0.0) + 2.2
    if not scores:
        return _fallback_genre(rec)
    return max(scores.items(), key=lambda kv: kv[1])[0]


def is_chinese(rec: dict) -> bool:
    cc = (rec.get("countrycode") or rec.get("cc") or "").upper()
    if cc in ("CN", "TW", "HK", "MO"):
        return True
    hay = (rec.get("language", "") + " " + rec.get("tags", "") + " " + rec.get("name", "")).lower()
    return any(m in hay for m in CHINESE_MARKERS) or bool(CJK.search(rec.get("name", "")))


def score_of(rec: dict) -> float:
    br = rec.get("bitrate") or 0
    sc = 0.0
    sc += min(rec.get("votes", 0), 400) * 0.85
    sc += min(rec.get("clicks") or rec.get("clickcount") or 0, 4000) * 0.10
    sc += min(br, 320) * 0.45
    if rec.get("homepage"):
        sc += 6
    if rec.get("favicon"):
        sc += 3
    if rec.get("icy_name"):
        sc += 4
    codec = (rec.get("real_codec") or rec.get("codec") or "").lower()
    if codec in ("mp3", "aac", "aac+"):
        sc += 6
    if rec.get("channels") == 2:
        sc += 4
    if is_chinese(rec):
        sc += 5
    if CJK.search(rec.get("name", "") or ""):
        sc += 6
    return sc


def url_key(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def name_country_key(name: str, cc: str) -> tuple[str, str]:
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (name or "").lower())[:28]
    return (compact, (cc or "").upper())


def strip_station(station: dict) -> dict:
    out = {key: station.get(key) for key in STATION_FIELDS}
    out["extra"] = True
    return out


def station_from_source(raw: dict) -> dict | None:
    """Turn a harvest/verify or radio-browser row into an app station, or None."""
    if raw.get("lastcheckok") is not None and int(raw.get("lastcheckok") or 0) == 0:
        return None
    if raw.get("ok") is False:
        return None
    name = clean_name(raw.get("name", "") or "")
    if not name or BAD_NAME.search(name):
        return None
    url = (raw.get("url_resolved") or raw.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    cc = (raw.get("countrycode") or raw.get("cc") or "").upper()
    codec = (raw.get("real_codec") or raw.get("codec") or "").upper()
    try:
        bitrate = int(raw.get("bitrate") or 0)
    except (TypeError, ValueError):
        bitrate = 0
    try:
        channels = int(raw.get("channels") or 0)
    except (TypeError, ValueError):
        channels = 0
    try:
        votes = int(raw.get("votes") or 0)
    except (TypeError, ValueError):
        votes = 0
    try:
        clicks = int(raw.get("clicks") or raw.get("clickcount") or 0)
    except (TypeError, ValueError):
        clicks = 0
    src = dict(raw)
    src["name"] = name
    src["countrycode"] = cc
    return {
        "name": name,
        "url": url,
        "genre": classify(src),
        "country": country_zh(cc, raw.get("country") or ""),
        "cc": cc,
        "region": {"CN": "cn", "HK": "hk", "TW": "tw", "MO": "mo"}.get(cc, ""),
        "state": norm_text(raw.get("state") or ""),
        "language": language_zh(raw.get("language") or "") or norm_text(raw.get("language") or ""),
        "tags": norm_text(raw.get("tags") or ""),
        "homepage": (raw.get("homepage") or "").strip(),
        "favicon": (raw.get("favicon") or "").strip(),
        "codec": codec,
        "bitrate": bitrate,
        "sample_rate": str(raw.get("sample_rate") or ""),
        "channels": channels,
        "votes": votes,
        "clicks": clicks,
        "zh": is_chinese(src),
        "score": round(score_of(src), 2),
        "extra": True,
        "custom": False,
    }


def select_additions(
    pool: list[dict],
    existing: list[dict],
    *,
    max_total: int = LIVE_MAX,
    per_genre: int = LIVE_PER_GENRE,
    per_genre_hard: int = LIVE_PER_GENRE_HARD,
    per_country: int = LIVE_PER_COUNTRY,
    priority: list[tuple[str, int]] | None = None,
) -> list[dict]:
    """Grow `existing` toward `max_total` using the same three-pass caps.

    Never removes a station that is already in the catalogue.
    `max_total` / genre / country caps of 0 mean unlimited.
    """
    if max_total > 0 and len(existing) >= max_total:
        return []
    have_url = {url_key(s.get("url", "")) for s in existing}
    have_nc = {name_country_key(s.get("name", ""), s.get("cc", "")) for s in existing}
    candidates = []
    seen_url: set[str] = set()
    seen_nc: set[tuple[str, str]] = set()
    for rec in pool:
        uk = url_key(rec.get("url", ""))
        nk = name_country_key(rec.get("name", ""), rec.get("cc", ""))
        if not uk or uk in have_url or uk in seen_url:
            continue
        if nk[0] and (nk in have_nc or nk in seen_nc):
            continue
        seen_url.add(uk)
        seen_nc.add(nk)
        candidates.append(rec)
    candidates.sort(key=lambda r: -float(r.get("score") or 0))

    chosen: list[dict] = []
    picked: set[str] = set()
    per_g: dict[str, int] = {}
    per_c: dict[str, int] = {}
    for s in existing:
        g = s.get("genre") or "varied"
        cc = s.get("cc") or "??"
        per_g[g] = per_g.get(g, 0) + 1
        per_c[cc] = per_c.get(cc, 0) + 1

    def take(rec: dict) -> None:
        picked.add(url_key(rec.get("url", "")))
        g = rec.get("genre") or "varied"
        cc = rec.get("cc") or "??"
        per_g[g] = per_g.get(g, 0) + 1
        per_c[cc] = per_c.get(cc, 0) + 1
        chosen.append(rec)

    rooms = (10 ** 9) if max_total <= 0 else max_total - len(existing)
    floors = priority if priority is not None else LIVE_PRIORITY

    def genre_full(g: str, hard: bool = False) -> bool:
        cap = per_genre_hard if hard else per_genre
        return cap > 0 and per_g.get(g, 0) >= cap

    def country_full(cc: str) -> bool:
        return per_country > 0 and per_c.get(cc, 0) >= per_country

    for cc, quota in floors:
        need = quota - per_c.get(cc, 0)
        if need <= 0:
            continue
        got = 0
        for rec in candidates:
            if got >= need or len(chosen) >= rooms:
                break
            if url_key(rec.get("url", "")) in picked:
                continue
            if (rec.get("cc") or "??") != cc:
                continue
            if genre_full(rec.get("genre") or "varied", hard=True):
                continue
            take(rec)
            got += 1
        if len(chosen) >= rooms:
            return chosen

    for rec in candidates:
        if len(chosen) >= rooms:
            break
        if url_key(rec.get("url", "")) in picked:
            continue
        g = rec.get("genre") or "varied"
        cc = rec.get("cc") or "??"
        if genre_full(g) or country_full(cc):
            continue
        take(rec)

    for rec in candidates:
        if len(chosen) >= rooms:
            break
        if url_key(rec.get("url", "")) in picked:
            continue
        g = rec.get("genre") or "varied"
        if genre_full(g, hard=True):
            continue
        take(rec)
    return chosen


def genres_meta(stations: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for s in stations:
        g = s.get("genre") or "varied"
        counts[g] = counts.get(g, 0) + 1
    rows = [
        {"key": k, "zh": zh, "en": en, "count": counts.get(k, 0)}
        for k, zh, en, _ in GENRES
    ]
    rows.append({
        "key": "varied", "zh": "综合电台", "en": "VARIED",
        "count": counts.get("varied", 0),
    })
    return [g for g in rows if g["count"] > 0]


GENRE_ZH = {key: zh for key, zh, _en, _kws in GENRES}
GENRE_ZH["varied"] = "综合电台"
GENRE_EN = {key: en for key, _zh, en, _kws in GENRES}
GENRE_EN["varied"] = "VARIED"

GENRE_CHOICES = [(key, zh) for key, zh, _en, _kws in GENRES] + [("varied", "综合电台")]


def countries_meta(stations: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for s in stations:
        name = s.get("country") or "其他"
        counts[name] = counts.get(name, 0) + 1
    return sorted(
        [{"name": k, "count": v} for k, v in counts.items()],
        key=lambda d: -d["count"],
    )
