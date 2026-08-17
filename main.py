"""
天气
Class Widgets 2 天气插件：实时天气与气象局预警（数据来自中央气象台 NMC，无需 API Key）。
"""

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ClassWidgets.SDK import CW2Plugin, PluginAPI
from PySide6.QtCore import QThread, Signal, Property, Slot

BASE = "https://www.nmc.cn/rest"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}
# 预警级别优先级（值越小越严重）
LEVEL_PRIORITY = {"红": 0, "橙": 1, "黄": 2, "蓝": 3, "白": 4}
SUFFIXES = ("特别行政区", "自治区", "自治州", "自治县", "自治旗", "地区", "盟", "市", "区", "县", "省")


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    """读取缓存索引，没有则构建并落盘"""
    try:
        if path.exists():
            index = json.loads(path.read_text(encoding="utf-8"))
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


def fetch_weather(city_name, index):
    """解析城市并抓取天气与预警"""
    entry = resolve_city(index, city_name)
    if not entry:
        raise ValueError(f"未找到城市：{city_name}")
    data = _get_json(f"{BASE}/weather?stationid={entry['code']}")
    payload = data.get("data") or {}
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
        try:
            return str(round(float(value)))
        except (TypeError, ValueError):
            return "--"

    # 过滤接口哨兵值 9999（无数据）
    direct = wind.get("direct") or ""
    if direct == "9999":
        direct = ""
    power = wind.get("power") or ""
    if power == "9999":
        power = ""
    humidity = w.get("humidity") or "--"
    if humidity not in ("--", "9999"):
        humidity = _num(humidity)

    return {
        "city": station.get("city") or entry["city"],
        "province": station.get("province") or entry["province"],
        "temp": _num(w.get("temperature")),
        "info": w.get("info") or "--",
        "wind": f"{direct} {power}".strip() or "--",
        "hi": str(day.get("temperature") or "--"),
        "lo": str(night.get("temperature") or "--"),
        "feel": _num(w.get("feelst")) if w.get("feelst") not in (None, "") else "",
        "humidity": humidity,
        "alerts": fetch_alerts(entry["province"], entry["city"]),
        "publish_time": real.get("publish_time") or "",
    }


class FetchWorker(QThread):
    """后台抓取线程：加载城市索引 -> 天气 + 预警"""

    ok = Signal(dict)
    fail = Signal(str)

    def __init__(self, city_name, index_file, parent=None):
        super().__init__(parent)
        self.city_name = city_name
        self.index_file = index_file

    def run(self):
        try:
            index = _load_index_cached(self.index_file)
            result = fetch_weather(self.city_name, index)
            self.ok.emit(result)
        except Exception as e:
            self.fail.emit(str(e))


class Plugin(CW2Plugin):
    """天气小组件"""

    weatherChanged = Signal()

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
        self._worker = None
        self._index_file = Path(__file__).resolve().parent / ".station_index.json"

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

    @Slot(str)
    def refresh(self, city):
        """按城市名刷新天气与预警（后台线程，不阻塞界面）"""
        if self._worker and self._worker.isRunning():
            return
        city = (city or "").strip()
        if not city:
            self._status = "need_city"
            self.weatherChanged.emit()
            return
        self._status = "loading"
        self.weatherChanged.emit()
        self._worker = FetchWorker(city, self._index_file, self)
        self._worker.ok.connect(self._on_ok)
        self._worker.fail.connect(self._on_fail)
        self._worker.start()

    def _on_ok(self, data):
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
            widget_id="com.laoshuikaixue.weather",
            name="天气",
            qml_path="qml/weather.qml",
            backend_obj=self,
            settings_qml="qml/weather-settings.qml",
            default_settings={
                "city": "",          # 城市名（如：北京 / 成都）
                "refresh_interval": 30,  # 自动刷新间隔（分钟）
                "show_alerts": True,     # 显示气象预警
            },
        )
        print("[weather] 插件已加载")

    def on_unload(self):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        print("[weather] 插件已卸载")
