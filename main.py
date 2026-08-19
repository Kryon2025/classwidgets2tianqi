"""
天气
Class Widgets 2 天气插件：实时天气与气象局预警（数据来自中央气象台 NMC + 中国天气网双源交叉校验，无需 API Key）。
"""

import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ClassWidgets.SDK import CW2Plugin, PluginAPI
from loguru import logger
from PySide6.QtCore import QThread, Signal, Property, Slot

BASE = "https://www.nmc.cn/rest"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}
CN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "http://www.weather.com.cn/",
}
# 预警级别优先级（值越小越严重）
LEVEL_PRIORITY = {"红": 0, "橙": 1, "黄": 2, "蓝": 3, "白": 4}
SUFFIXES = ("特别行政区", "自治区", "自治州", "自治县", "自治旗", "地区", "盟", "市", "区", "县", "省")


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url, timeout=10):
    """拉取原始文本（中国天气网接口返回 JS 变量而非纯 JSON）。"""
    req = urllib.request.Request(url, headers=CN_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── IP 定位（自动获取当前位置）──────────────────────
IP_LOCATE_URLS = (
    "http://ip-api.com/json/?lang=zh-CN",
    "http://ip.useragentinfo.com/json",
)


def locate_city_by_ip():
    """通过公网 IP 定位当前城市，返回城市名（市级）或 None。

    城市名优先取市级（ip-api 的 city / useragentinfo 的 province），
    供 NMC / 中国天气网等按城市名索引的源解析站点。
    """
    for url in IP_LOCATE_URLS:
        try:
            d = _get_json(url, timeout=8)
            if d.get("status") == "success":          # ip-api.com
                return d.get("city") or d.get("regionName") or None
            if d.get("success") and d.get("lat"):     # ip.useragentinfo.com
                return d.get("province") or d.get("city") or None
        except Exception:
            continue
    return None


def _norm(name):
    """去掉行政区后缀，便于名称匹配"""
    for suf in SUFFIXES:
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def build_city_index():
    """构建城市索引：[{city, code, province}]，省-市两级并行抓取"""
    provinces = _get_json(f"{BASE}/province/all")
    entries = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_get_json, f"{BASE}/province/{p['code']}") for p in provinces]
        for fut, p in zip(futures, provinces):
            try:
                cities = fut.result()
            except Exception:
                continue
            for c in cities:
                entries.append({"city": c["city"], "code": c["code"], "province": p["name"]})
    return entries


def _load_index_cached(path):
    """读取缓存索引，没有则构建并落盘。

    旧版索引的 station code 是数字（如 58362），2026 年 NMC 接口改版后
    数字 code 一律返回空数据，因此检测到旧格式时强制重建（新格式为字母 code）。
    """
    try:
        if path.exists():
            index = json.loads(path.read_text(encoding="utf-8"))
            if index and re.match(r"^\d+$", str(index[0].get("code", ""))):
                print("[weather] 检测到旧版数字 station code 索引，触发重建")
                index = None
            if index:
                return index
    except Exception:
        pass
    index = build_city_index()
    try:
        path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return index


def resolve_city(index, name):
    """按城市名匹配站点：精确 > 归一化 > 包含"""
    name = (name or "").strip()
    if not name:
        return None
    for e in index:
        if e["city"] == name:
            return e
    n = _norm(name)
    for e in index:
        if _norm(e["city"]) == n:
            return e
    for e in index:
        if n and n in e["city"]:
            return e
    return None


def _alert_level(title):
    for w in ("红色", "橙色", "黄色", "蓝色", "白色"):
        if w in title:
            return w[0]
    return ""


def fetch_alerts(province, city):
    """拉取本省预警列表并按城市名过滤，返回 [{title, level, time}]（最多 3 条，最严重在前）"""
    result = []
    for page in range(1, 4):  # 最多翻 3 页
        url = (f"{BASE}/findAlarm?pageNo={page}&pageSize=50&signaltype=&signallevel="
               f"&province={urllib.parse.quote(province)}")
        try:
            data = _get_json(url)
        except Exception:
            break
        alarm_list = ((data.get("data") or {}).get("page") or {}).get("list") or []
        if not alarm_list:
            break
        for a in alarm_list:
            title = a.get("title") or ""
            if city and city in title:
                result.append({
                    "title": title,
                    "level": _alert_level(title),
                    "time": a.get("issuetime") or "",
                })
        if len(result) >= 3:
            break
    result.sort(key=lambda a: LEVEL_PRIORITY.get(a["level"], 9))
    return result[:3]


# ── 中国天气网（weather.com.cn）补充源 ──────────────────────────────

_CN_CODE_CACHE: dict = {}


def _get_cn_code(city_name):
    """城市名 → 中国天气网城市 code（toy1 搜索，内存缓存）。"""
    if city_name in _CN_CODE_CACHE:
        return _CN_CODE_CACHE[city_name]
    try:
        url = f"http://toy1.weather.com.cn/search?cityname={urllib.parse.quote(city_name)}"
        text = _get_text(url, timeout=8)
        refs = re.findall(r'"ref":"(\d+)~([^~]*)~([^~]*)~', text)
        code = None
        for cid, pinyin, cn_name in refs:
            if cn_name == city_name:  # 精确匹配中文名
                code = cid
                break
        if code is None and refs:
            code = refs[0][0]
        _CN_CODE_CACHE[city_name] = code
        return code
    except Exception as e:
        print(f"[weather] 中国天气网城市解析失败: {e}")
        return None


def _fetch_cn_weather(city_name):
    """中国天气网：实时温度/湿度/风力/天气 + 当日最低温。失败返回 None。"""
    code = _get_cn_code(city_name)
    if not code:
        return None
    text = _get_text(
        f"http://d1.weather.com.cn/weather_index/{code}.html?_={int(time.time() * 1000)}",
        timeout=8)
    sk = {}
    dz = {}
    m = re.search(r"var dataSK\s*=\s*(\{.*?\});", text, re.S)
    if m:
        try:
            sk = json.loads(m.group(1))
        except Exception:
            sk = {}
    m2 = re.search(r"var cityDZ\s*=\s*(\{.*?\});", text, re.S)
    if m2:
        try:
            dz = json.loads(m2.group(1))
        except Exception:
            dz = {}
    dz_info = dz.get("weatherinfo") or {}
    if not sk and not dz_info:
        return None
    return {
        "temp": sk.get("temp") if sk else None,
        "humidity": (sk.get("SD") or "").rstrip("%") if sk else None,
        "wind": f"{sk.get('WD') or ''} {sk.get('WS') or ''}".strip() if sk else "",
        "info": sk.get("weather") if sk else None,
        "low": dz_info.get("tempn"),
    }


# ── 数据校验（确保每个显示字段正常）──────────────────────────────

def _valid_temp(value):
    """温度合理性校验：过滤哨兵（999/9999）与物理范围外（±60°C）的值。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if abs(f) >= 999 or f < -60 or f > 60:
        return None
    return f


def _valid_humidity(value):
    """湿度合理性校验：0~100%。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f < 0 or f > 100:
        return None
    return f


# ── 双源融合 ─────────────────────────────────────────────────

def fetch_weather(city_name, index):
    """双源拉取并融合：NMC（主，含体感与预警）+ 中国天气网（校验/兜底）。

    返回统一结构，所有显示字段均经过哨兵过滤与合理性校验。
    """
    nmc = _parse_nmc(city_name, index)
    cn = None
    try:
        cn = _fetch_cn_weather(city_name)
    except Exception as e:
        print(f"[weather] 中国天气网获取失败: {e}")
    if nmc is None and cn is None:
        raise ValueError(f"未找到城市：{city_name}")
    return _merge_weather(nmc, cn, city_name)


def _parse_nmc(city_name, index):
    """NMC 数据源解析（含 9999 哨兵与华氏异常处理），失败返回 None。"""
    entry = resolve_city(index, city_name)
    if not entry:
        return None
    try:
        data = _get_json(f"{BASE}/weather?stationid={entry['code']}")
        payload = data.get("data")
        # NMC 改版后旧数字 code 返回空 data：视为本数据源失败，交给中国天气网兜底
        if not payload:
            print(f"[weather] NMC 对 stationid={entry['code']} 返回空数据")
            return None
        real = payload.get("real") or {}
        predict = payload.get("predict") or {}
        station = real.get("station") or {}
        w = real.get("weather") or {}
        wind = real.get("wind") or {}
        detail = predict.get("detail") or []
        today = detail[0] if detail else {}
        day = (today.get("day") or {}).get("weather") or {}
        night = (today.get("night") or {}).get("weather") or {}

        def _num(value):
            f = _valid_temp(value)
            return str(round(f)) if f is not None else "--"

        # 过滤接口哨兵值 9999（无数据）
        direct = wind.get("direct") or ""
        if direct == "9999":
            direct = ""
        power = wind.get("power") or ""
        if power == "9999":
            power = ""

        # 体感温度：哨兵/缺失不显示；与当前温度相差过大时疑似华氏度或异常值，尝试转换
        feel = ""
        feel_raw = w.get("feelst")
        if feel_raw not in (None, ""):
            feel_f = _num(feel_raw)
            if feel_f != "--":
                temp_raw = w.get("temperature")
                if temp_raw not in (None, ""):
                    t = _valid_temp(temp_raw)
                    if t is not None and abs(float(feel_raw) - t) > 20:
                        celsius = (float(feel_raw) - 32) * 5 / 9
                        feel_f = str(round(celsius)) if abs(celsius - t) <= 20 else ""
                feel = feel_f

        humidity = w.get("humidity") or "--"
        if humidity not in ("--", "9999"):
            humidity = _num(humidity)

        # 最高气温：当天白天预报未发布/已归档（NMC 夜间返回 9999）时，
        # 用当前实时温度兜底，避免显示 9999 或空值
        hi = _num(day.get("temperature"))
        hi_forecast = hi != "--"
        if not hi_forecast:
            hi = _num(w.get("temperature"))
            if hi == "--":
                hi = _num(night.get("temperature"))

        return {
            "city": station.get("city") or entry["city"],
            "province": station.get("province") or entry["province"],
            "temp": _num(w.get("temperature")),
            "info": w.get("info") or "--",
            "wind": f"{direct} {power}".strip() or "--",
            "hi": hi,
            "hi_forecast": hi_forecast,
            "lo": _num(night.get("temperature")),
            "feel": feel,
            "humidity": humidity,
            "alerts": fetch_alerts(entry["province"], entry["city"]),
            "publish_time": real.get("publish_time") or "",
        }
    except Exception as e:
        print(f"[weather] NMC 获取失败: {e}")
        return None


def _merge_weather(nmc, cn, city_name):
    """融合双源数据并做合理性校验，保证每个显示字段正常。"""
    nmc = nmc or {}
    cn = cn or {}

    def tstr(v):
        f = _valid_temp(v)
        return str(round(f)) if f is not None else None

    def hstr(v):
        f = _valid_humidity(v)
        return str(round(f)) if f is not None else None

    # 实时温度：NMC 优先，中国天气网兜底；差异 >8° 视为数据冲突，以 NMC 为准
    t_nmc = tstr(nmc.get("temp"))
    t_cn = tstr(cn.get("temp"))
    if t_nmc and t_cn and abs(float(t_nmc) - float(t_cn)) > 8:
        print(f"[weather] 实时温度双源差异过大: NMC {t_nmc}° vs 中国天气网 {t_cn}°，以 NMC 为准")
    temp = t_nmc or t_cn

    info = (nmc.get("info") or cn.get("info")) or "--"
    # NMC 改版后天气描述可能返回占位符 "-"，此时用中国天气网兜底
    if info in ("--", "-"):
        info = cn.get("info") or "--"
    wind = (nmc.get("wind") or cn.get("wind")) or "--"
    humidity = hstr(nmc.get("humidity")) if nmc.get("humidity") not in (None, "--") else None
    if not humidity and cn.get("humidity") not in (None, ""):
        humidity = hstr(cn.get("humidity"))
    humidity = humidity or "--"

    # 体感（NMC 独有）：无效则留空（QML 不渲染）
    feel = nmc.get("feel") or ""
    f = tstr(feel)
    if not f:
        feel = ""
    elif temp and temp != "--" and abs(float(f) - float(temp)) > 20:
        feel = ""

    # 最高/最低：预报优先，中国天气网补最低，保证 hi >= lo
    hi = tstr(nmc.get("hi"))
    hi_forecast = bool(hi) and bool(nmc.get("hi_forecast"))
    lo = tstr(nmc.get("lo"))
    if not lo:
        lo = tstr(cn.get("low"))
    if not hi and temp and temp != "--":
        hi = temp
    if hi and lo and float(hi) < float(lo):
        hi = lo
        hi_forecast = False  # 用最低值抬升过，不再视为可靠预报

    return {
        "city": nmc.get("city") or city_name,
        "province": nmc.get("province") or "",
        "temp": temp or "--",
        "info": info,
        "wind": wind,
        "hi": hi or "--",
        "hi_forecast": hi_forecast,
        "lo": lo or "--",
        "feel": feel,
        "humidity": humidity,
        "alerts": nmc.get("alerts") or [],
        "publish_time": nmc.get("publish_time") or "",
    }


class FetchWorker(QThread):
    """后台抓取线程：加载城市索引 -> 天气 + 预警"""

    ok = Signal(dict)
    fail = Signal(str)

    def __init__(self, city_name, index_file, auto_location=False, parent=None):
        super().__init__(parent)
        self.city_name = city_name
        self.index_file = index_file
        self.auto_location = auto_location

    def run(self):
        try:
            index = _load_index_cached(self.index_file)
            city = self.city_name
            if self.auto_location:
                ip_city = locate_city_by_ip()
                if not ip_city:
                    raise ValueError(
                        "自动定位失败：无法获取当前位置，请检查网络，"
                        "或在组件设置中关闭自动定位并手动输入城市"
                    )
                city = ip_city
            result = fetch_weather(city, index)
            self.ok.emit(result)
        except Exception as e:
            self.fail.emit(str(e))


class Plugin(CW2Plugin):
    """天气小组件"""

    weatherChanged = Signal()
    configChanged = Signal()

    def __init__(self, api: PluginAPI):
        super().__init__(api)
        self._status = "need_city"  # need_city / loading / ok / error
        self._city = ""
        self._temp = "--"
        self._info = "--"
        self._wind = "--"
        self._hi = "--"
        self._lo = "--"
        self._feel = ""
        self._humidity = "--"
        self._alert_count = 0
        self._alert_title = ""
        self._alert_level = ""
        self._publish_time = ""
        self._today_hi = ""
        self._today_hi_date = ""
        self._worker = None
        self._index_file = Path(__file__).resolve().parent / ".station_index.json"
        self._auto_file = Path(__file__).resolve().parent / ".weather_auto.json"
        self._auto_location = True
        self._load_auto_location()
        logger.debug(f"[weather.debug] __init__ auto={self._auto_location} "
                     f"file={self._auto_file}")

    def _load_auto_location(self):
        """读取自动定位开关（旧实例无文件时默认开启）。"""
        try:
            if self._auto_file.exists():
                self._auto_location = bool(
                    json.loads(self._auto_file.read_text(encoding="utf-8")).get(
                        "auto_location", True
                    )
                )
        except Exception:
            pass
        logger.debug(f"[weather.debug] _load_auto_location -> {self._auto_location}")

    def _save_auto_location(self):
        try:
            self._auto_file.write_text(
                json.dumps({"auto_location": self._auto_location}, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug(f"[weather.debug] _save_auto_location OK -> {self._auto_location}")
        except Exception as e:
            logger.error(f"[weather.debug] _save_auto_location FAILED: {e!r}")

    # ---- QML 可读属性 ----
    def _get_status(self):
        return self._status

    def _get_city(self):
        return self._city

    def _get_temp(self):
        return self._temp

    def _get_info(self):
        return self._info

    def _get_wind(self):
        return self._wind

    def _get_hilo(self):
        return f"最高 {self._hi}°  最低 {self._lo}°"

    def _get_feel(self):
        return self._feel

    def _get_humidity(self):
        return self._humidity

    def _get_alert_count(self):
        return self._alert_count

    def _get_alert_title(self):
        return self._alert_title

    def _get_alert_level(self):
        return self._alert_level

    def _get_publish(self):
        return self._publish_time

    weatherStatus = Property(str, _get_status, notify=weatherChanged)
    cityName = Property(str, _get_city, notify=weatherChanged)
    tempText = Property(str, _get_temp, notify=weatherChanged)
    weatherText = Property(str, _get_info, notify=weatherChanged)
    windText = Property(str, _get_wind, notify=weatherChanged)
    hiLoText = Property(str, _get_hilo, notify=weatherChanged)
    feelText = Property(str, _get_feel, notify=weatherChanged)
    humidityText = Property(str, _get_humidity, notify=weatherChanged)
    alertCount = Property(int, _get_alert_count, notify=weatherChanged)
    alertTitle = Property(str, _get_alert_title, notify=weatherChanged)
    alertLevel = Property(str, _get_alert_level, notify=weatherChanged)
    publishText = Property(str, _get_publish, notify=weatherChanged)

    def _get_auto_location(self):
        return self._auto_location

    autoLocation = Property(bool, _get_auto_location, notify=weatherChanged)

    @Slot(result=dict)
    def getConfig(self) -> dict:
        """返回当前配置（供组件设置页读取初始值）。"""
        logger.debug(f"[weather.debug] getConfig -> auto_location={self._auto_location}")
        return {"auto_location": self._auto_location}

    @Slot(bool)
    def setAutoLocation(self, value: bool) -> None:
        """切换自动定位并立即按新模式刷新。"""
        logger.debug(f"[weather.debug] setAutoLocation({value}) current={self._auto_location}")
        value = bool(value)
        if value == self._auto_location:
            return
        self._auto_location = value
        self._save_auto_location()
        self.configChanged.emit()
        self.refresh("")

    @Slot(str)
    def refresh(self, city):
        """按城市名刷新天气与预警（后台线程，不阻塞界面）"""
        logger.debug(f"[weather.debug] refresh({city!r}) auto={self._auto_location} "
                     f"busy={self._worker and self._worker.isRunning()}")
        if self._worker and self._worker.isRunning():
            return
        city = (city or "").strip()
        if not self._auto_location and not city:
            self._status = "need_city"
            self.weatherChanged.emit()
            return
        self._status = "loading"
        self.weatherChanged.emit()
        self._worker = FetchWorker(city, self._index_file, self._auto_location, self)
        self._worker.ok.connect(self._on_ok)
        self._worker.fail.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self, data):
        # 当天最高温：白天拿到真实预报时缓存；夜间预报归档（回退值）时复用缓存
        today = dt.date.today().isoformat()
        if data.get("hi_forecast") and data["hi"] != "--":
            self._today_hi = data["hi"]
            self._today_hi_date = today
        elif self._today_hi_date == today and self._today_hi:
            try:
                data["hi"] = str(max(int(data["hi"]), int(self._today_hi)))
            except ValueError:
                data["hi"] = self._today_hi
        self._city = data["city"]
        self._temp = data["temp"]
        self._info = data["info"]
        self._wind = data["wind"]
        self._hi = data["hi"]
        self._lo = data["lo"]
        self._feel = data["feel"]
        self._humidity = data["humidity"]
        self._publish_time = data["publish_time"]
        alerts = data.get("alerts") or []
        self._alert_count = len(alerts)
        self._alert_title = alerts[0]["title"] if alerts else ""
        self._alert_level = alerts[0]["level"] if alerts else ""
        self._status = "ok"
        self.weatherChanged.emit()
        print(f"[weather] 更新成功: {self._city} {self._temp}° {self._info} 预警{self._alert_count}条")

    def _on_fail(self, msg):
        print(f"[weather] 获取失败: {msg}")
        self._status = "error"
        self.weatherChanged.emit()

    def on_load(self):
        super().on_load()
        self.api.widgets.register(
            widget_id="com.kryon.weather",
            name="天气",
            qml_path="qml/weather.qml",
            backend_obj=self,
            settings_qml="qml/weather-settings.qml",
            default_settings={
                "city": "",          # 城市名（如：北京 / 成都）
                "auto_location": True,   # 自动定位当前位置（IP 定位，免配置）
                "refresh_interval": 30,  # 自动刷新间隔（分钟）
                "show_alerts": True,     # 显示气象预警
                "alert_show_time": 5,    # 预警播报时长（秒），到时自动收起
            },
        )
        print("[weather] 插件已加载")

    def on_unload(self):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        print("[weather] 插件已卸载")
