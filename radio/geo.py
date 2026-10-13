"""Country and language labels in Simplified Chinese."""
from __future__ import annotations

import re
import unicodedata

CJK = re.compile(r"[\u4e00-\u9fff]")

COUNTRY_ZH: dict[str, str] = {
    "AD": "安道尔", "AE": "阿联酋", "AF": "阿富汗", "AG": "安提瓜和巴布达",
    "AI": "安圭拉", "AL": "阿尔巴尼亚", "AM": "亚美尼亚", "AO": "安哥拉",
    "AQ": "南极洲", "AR": "阿根廷", "AS": "美属萨摩亚", "AT": "奥地利",
    "AU": "澳大利亚", "AW": "阿鲁巴", "AX": "奥兰", "AZ": "阿塞拜疆",
    "BA": "波黑", "BB": "巴巴多斯", "BD": "孟加拉国", "BE": "比利时",
    "BF": "布基纳法索", "BG": "保加利亚", "BH": "巴林", "BI": "布隆迪",
    "BJ": "贝宁", "BL": "圣巴泰勒米", "BM": "百慕大", "BN": "文莱",
    "BO": "玻利维亚", "BQ": "荷属加勒比", "BR": "巴西", "BS": "巴哈马",
    "BT": "不丹", "BV": "布韦岛", "BW": "博茨瓦纳", "BY": "白俄罗斯",
    "BZ": "伯利兹", "CA": "加拿大", "CC": "科科斯群岛", "CD": "刚果（金）",
    "CF": "中非", "CG": "刚果（布）", "CH": "瑞士", "CI": "科特迪瓦",
    "CK": "库克群岛", "CL": "智利", "CM": "喀麦隆", "CN": "中国",
    "CO": "哥伦比亚", "CR": "哥斯达黎加", "CU": "古巴", "CV": "佛得角",
    "CW": "库拉索", "CX": "圣诞岛", "CY": "塞浦路斯", "CZ": "捷克",
    "DE": "德国", "DJ": "吉布提", "DK": "丹麦", "DM": "多米尼克",
    "DO": "多米尼加", "DZ": "阿尔及利亚", "EC": "厄瓜多尔", "EE": "爱沙尼亚",
    "EG": "埃及", "EH": "西撒哈拉", "ER": "厄立特里亚", "ES": "西班牙",
    "ET": "埃塞俄比亚", "FI": "芬兰", "FJ": "斐济", "FK": "福克兰群岛",
    "FM": "密克罗尼西亚", "FO": "法罗群岛", "FR": "法国", "GA": "加蓬",
    "GB": "英国", "GD": "格林纳达", "GE": "格鲁吉亚", "GF": "法属圭亚那",
    "GG": "根西", "GH": "加纳", "GI": "直布罗陀", "GL": "格陵兰",
    "GM": "冈比亚", "GN": "几内亚", "GP": "瓜德罗普", "GQ": "赤道几内亚",
    "GR": "希腊", "GS": "南乔治亚", "GT": "危地马拉", "GU": "关岛",
    "GW": "几内亚比绍", "GY": "圭亚那", "HK": "中国香港", "HM": "赫德岛",
    "HN": "洪都拉斯", "HR": "克罗地亚", "HT": "海地", "HU": "匈牙利",
    "ID": "印度尼西亚", "IE": "爱尔兰", "IL": "以色列", "IM": "马恩岛",
    "IN": "印度", "IO": "英属印度洋领地", "IQ": "伊拉克", "IR": "伊朗",
    "IS": "冰岛", "IT": "意大利", "JE": "泽西", "JM": "牙买加",
    "JO": "约旦", "JP": "日本", "KE": "肯尼亚", "KG": "吉尔吉斯斯坦",
    "KH": "柬埔寨", "KI": "基里巴斯", "KM": "科摩罗", "KN": "圣基茨和尼维斯",
    "KP": "朝鲜", "KR": "韩国", "KW": "科威特", "KY": "开曼群岛",
    "KZ": "哈萨克斯坦", "LA": "老挝", "LB": "黎巴嫩", "LC": "圣卢西亚",
    "LI": "列支敦士登", "LK": "斯里兰卡", "LR": "利比里亚", "LS": "莱索托",
    "LT": "立陶宛", "LU": "卢森堡", "LV": "拉脱维亚", "LY": "利比亚",
    "MA": "摩洛哥", "MC": "摩纳哥", "MD": "摩尔多瓦", "ME": "黑山",
    "MF": "法属圣马丁", "MG": "马达加斯加", "MH": "马绍尔群岛", "MK": "北马其顿",
    "ML": "马里", "MM": "缅甸", "MN": "蒙古", "MO": "中国澳门",
    "MP": "北马里亚纳", "MQ": "马提尼克", "MR": "毛里塔尼亚", "MS": "蒙特塞拉特",
    "MT": "马耳他", "MU": "毛里求斯", "MV": "马尔代夫", "MW": "马拉维",
    "MX": "墨西哥", "MY": "马来西亚", "MZ": "莫桑比克", "NA": "纳米比亚",
    "NC": "新喀里多尼亚", "NE": "尼日尔", "NF": "诺福克岛", "NG": "尼日利亚",
    "NI": "尼加拉瓜", "NL": "荷兰", "NO": "挪威", "NP": "尼泊尔",
    "NR": "瑙鲁", "NU": "纽埃", "NZ": "新西兰", "OM": "阿曼",
    "PA": "巴拿马", "PE": "秘鲁", "PF": "法属波利尼西亚", "PG": "巴布亚新几内亚",
    "PH": "菲律宾", "PK": "巴基斯坦", "PL": "波兰", "PM": "圣皮埃尔和密克隆",
    "PN": "皮特凯恩", "PR": "波多黎各", "PS": "巴勒斯坦", "PT": "葡萄牙",
    "PW": "帕劳", "PY": "巴拉圭", "QA": "卡塔尔", "RE": "留尼汪",
    "RO": "罗马尼亚", "RS": "塞尔维亚", "RU": "俄罗斯", "RW": "卢旺达",
    "SA": "沙特阿拉伯", "SB": "所罗门群岛", "SC": "塞舌尔", "SD": "苏丹",
    "SE": "瑞典", "SG": "新加坡", "SH": "圣赫勒拿", "SI": "斯洛文尼亚",
    "SJ": "斯瓦尔巴", "SK": "斯洛伐克", "SL": "塞拉利昂", "SM": "圣马力诺",
    "SN": "塞内加尔", "SO": "索马里", "SR": "苏里南", "SS": "南苏丹",
    "ST": "圣多美和普林西比", "SV": "萨尔瓦多", "SX": "荷属圣马丁", "SY": "叙利亚",
    "SZ": "斯威士兰", "TC": "特克斯和凯科斯", "TD": "乍得", "TF": "法属南部领地",
    "TG": "多哥", "TH": "泰国", "TJ": "塔吉克斯坦", "TK": "托克劳",
    "TL": "东帝汶", "TM": "土库曼斯坦", "TN": "突尼斯", "TO": "汤加",
    "TR": "土耳其", "TT": "特立尼达和多巴哥", "TV": "图瓦卢", "TW": "中国台湾",
    "TZ": "坦桑尼亚", "UA": "乌克兰", "UG": "乌干达", "UM": "美国本土外小岛屿",
    "US": "美国", "UY": "乌拉圭", "UZ": "乌兹别克斯坦", "VA": "梵蒂冈",
    "VC": "圣文森特和格林纳丁斯", "VE": "委内瑞拉", "VG": "英属维尔京群岛",
    "VI": "美属维尔京群岛", "VN": "越南", "VU": "瓦努阿图", "WF": "瓦利斯和富图纳",
    "WS": "萨摩亚", "XK": "科索沃", "YE": "也门", "YT": "马约特",
    "ZA": "南非", "ZM": "赞比亚", "ZW": "津巴布韦",
}

# radio-browser sometimes stores the English country name without a code we know.
COUNTRY_EN_TO_ZH: dict[str, str] = {
    "the democratic republic of the congo": "刚果（金）",
    "democratic republic of the congo": "刚果（金）",
    "congo, democratic republic of the": "刚果（金）",
    "congo": "刚果（布）",
    "state of palestine": "巴勒斯坦",
    "palestine, state of": "巴勒斯坦",
    "palestine": "巴勒斯坦",
    "the cayman islands": "开曼群岛",
    "cayman islands": "开曼群岛",
    "the faroe islands": "法罗群岛",
    "faroe islands": "法罗群岛",
    "the united states minor outlying islands": "美国本土外小岛屿",
    "united states minor outlying islands": "美国本土外小岛屿",
    "guinea bissau": "几内亚比绍",
    "guinea-bissau": "几内亚比绍",
    "russian federation": "俄罗斯",
    "korea, republic of": "韩国",
    "korea, democratic people's republic of": "朝鲜",
    "iran, islamic republic of": "伊朗",
    "syrian arab republic": "叙利亚",
    "tanzania, united republic of": "坦桑尼亚",
    "moldova, republic of": "摩尔多瓦",
    "macedonia": "北马其顿",
    "bolivia, plurinational state of": "玻利维亚",
    "venezuela, bolivarian republic of": "委内瑞拉",
    "viet nam": "越南",
    "lao people's democratic republic": "老挝",
    "brunei darussalam": "文莱",
    "czech republic": "捷克",
    "united kingdom": "英国",
    "united states": "美国",
    "united states of america": "美国",
    "the netherlands": "荷兰",
    "holland": "荷兰",
}

LANGUAGE_ZH: dict[str, str] = {
    "english": "英语", "en": "英语", "german": "德语", "de": "德语", "deutsch": "德语",
    "french": "法语", "fr": "法语", "français": "法语", "francais": "法语",
    "spanish": "西班牙语", "es": "西班牙语", "español": "西班牙语", "espanol": "西班牙语",
    "portuguese": "葡萄牙语", "pt": "葡萄牙语", "italian": "意大利语", "it": "意大利语",
    "dutch": "荷兰语", "nl": "荷兰语", "nederlands": "荷兰语",
    "russian": "俄语", "ru": "俄语", "polish": "波兰语", "pl": "波兰语",
    "japanese": "日语", "ja": "日语", "jp": "日语", "korean": "韩语", "ko": "韩语", "kr": "韩语",
    "chinese": "中文", "zh": "中文", "mandarin": "普通话", "cantonese": "粤语",
    "arabic": "阿拉伯语", "ar": "阿拉伯语", "hindi": "印地语", "hi": "印地语",
    "turkish": "土耳其语", "tr": "土耳其语", "swedish": "瑞典语", "sv": "瑞典语",
    "norwegian": "挪威语", "no": "挪威语", "danish": "丹麦语", "da": "丹麦语",
    "finnish": "芬兰语", "fi": "芬兰语", "greek": "希腊语", "el": "希腊语",
    "hebrew": "希伯来语", "he": "希伯来语", "hungarian": "匈牙利语", "hu": "匈牙利语",
    "czech": "捷克语", "cs": "捷克语", "romanian": "罗马尼亚语", "ro": "罗马尼亚语",
    "ukrainian": "乌克兰语", "uk": "乌克兰语", "thai": "泰语", "th": "泰语",
    "vietnamese": "越南语", "vi": "越南语", "indonesian": "印尼语", "id": "印尼语",
    "malay": "马来语", "ms": "马来语", "catalan": "加泰罗尼亚语", "ca": "加泰罗尼亚语",
    "basque": "巴斯克语", "galician": "加利西亚语", "slovak": "斯洛伐克语", "sk": "斯洛伐克语",
    "croatian": "克罗地亚语", "hr": "克罗地亚语", "serbian": "塞尔维亚语", "sr": "塞尔维亚语",
    "bulgarian": "保加利亚语", "bg": "保加利亚语", "slovenian": "斯洛文尼亚语", "sl": "斯洛文尼亚语",
    "lithuanian": "立陶宛语", "lt": "立陶宛语", "latvian": "拉脱维亚语", "lv": "拉脱维亚语",
    "estonian": "爱沙尼亚语", "et": "爱沙尼亚语", "icelandic": "冰岛语", "is": "冰岛语",
    "irish": "爱尔兰语", "ga": "爱尔兰语", "welsh": "威尔士语", "cy": "威尔士语",
    "tagalog": "他加禄语", "filipino": "菲律宾语", "swahili": "斯瓦希里语",
    "persian": "波斯语", "farsi": "波斯语", "fa": "波斯语", "urdu": "乌尔都语",
    "bengali": "孟加拉语", "tamil": "泰米尔语", "telugu": "泰卢固语", "punjabi": "旁遮普语",
    "albanian": "阿尔巴尼亚语", "bosnian": "波斯尼亚语", "macedonian": "马其顿语",
    "georgian": "格鲁吉亚语", "armenian": "亚美尼亚语", "azerbaijani": "阿塞拜疆语",
    "kazakh": "哈萨克语", "uzbek": "乌兹别克语", "mongolian": "蒙古语",
    "khmer": "高棉语", "lao": "老挝语", "burmese": "缅甸语", "amharic": "阿姆哈拉语",
    "afrikaans": "南非荷兰语", "esperanto": "世界语", "latin": "拉丁语",
    "luxembourgish": "卢森堡语", "maltese": "马耳他语", "faroese": "法罗语",
    "haitian": "海地克里奥尔语", "creole": "克里奥尔语",
    "multilingual": "多语言", "various": "多种语言", "other": "其他",
}


def _fold_en(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    if text.startswith("the "):
        text = text[4:]
    return text


def country_zh(cc: str, fallback: str = "") -> str:
    code = (cc or "").strip().upper()
    if code in COUNTRY_ZH:
        return COUNTRY_ZH[code]
    raw = (fallback or "").strip()
    if raw and CJK.search(raw):
        return raw
    hit = COUNTRY_EN_TO_ZH.get(_fold_en(raw))
    if hit:
        return hit
    return raw or "其他"


def language_zh(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if CJK.search(text) and "," not in text and "/" not in text:
        return text
    parts = re.split(r"[,/;|]+", text)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        token = part.strip()
        if not token:
            continue
        label = LANGUAGE_ZH.get(token.casefold(), token)
        if label not in seen:
            seen.add(label)
            out.append(label)
    return "、".join(out)
