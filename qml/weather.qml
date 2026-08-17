import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick 2.15 as Quick
import RinUI
import ClassWidgets.Theme

Widget {
    id: root
    text: backend.cityName !== "" ? backend.cityName : qsTr("天气")

    // 固定组件宽度，保持与其他组件一致；高度用标准值
    implicitWidth: 280

    // 当前城市（设置里修改城市时自动刷新）
    property string currentCity: settings.city
    onCurrentCityChanged: backend.refresh(currentCity)

    // 预警级别颜色（红/橙/黄/蓝）
    property color levelColor: backend.alertLevel === "红" ? "#E64340" :
                               backend.alertLevel === "橙" ? "#F59A23" :
                               backend.alertLevel === "黄" ? "#E6A23C" : "#3B7BD0"
    // 是否有预警要显示
    property bool alertActive: settings.show_alerts && backend.alertCount > 0

    // 气象预警：灵动岛式弹出（由城市名右侧弹出并向右延伸），文字在胶囊直段内从右到左滚动播报；
    // 播报时长（默认 5 秒，设置页可调）结束后等当前一轮播完，再从右往左弹回城市后消失
    subtitle: [
        Rectangle {
            id: alertPill
            objectName: "alertPill"
            // 预警激活状态（用于在自身作用域触发弹出/收起）
            property bool pillActive: root.alertActive
            // 播报状态机：finishing=到时等待当前轮播完；collapsing=正在弹回收起（动画可见）；hidden=已消失
            property bool finishing: false
            property bool collapsing: false
            property bool hidden: false

            visible: pillActive && !hidden
            height: 22
            radius: height / 2
            color: root.levelColor
            clip: true
            // 无预警、或播报结束、或收起中宽度为 0；播报时按内容展开，最长 190
            width: pillActive && !hidden && !collapsing ? Math.min(190, alertLabel.implicitWidth + 28) : 0

            Behavior on width {
                NumberAnimation {
                    duration: 450
                    easing.type: Easing.OutBack
                    easing.overshoot: 1.6
                }
            }

            // 文字只在胶囊直段内滚动（左右各留出一个圆角半径），不会滚到圆形端部之外
            Item {
                id: tickerZone
                anchors {
                    left: parent.left
                    right: parent.right
                    verticalCenter: parent.verticalCenter
                    leftMargin: parent.radius
                    rightMargin: parent.radius
                }
                height: parent.height
                clip: true

                // 预警文字：从右侧进入、向左侧移出循环播报；内容放得下时静止居中
                Text {
                    id: alertLabel
                    text: "⚠ " + backend.alertTitle
                    color: "#ffffff"
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    y: (parent.height - height) / 2

                    NumberAnimation on x {
                        id: tickerAnim
                        loops: Animation.Infinite
                        running: false
                        from: tickerZone.width
                        to: -alertLabel.width
                        duration: (alertLabel.width + tickerZone.width) * 1000 / Math.max(1, 50)
                    }
                }

                // 到时后把当前这一轮播完（从当前位置以原速度滚到结尾），结束后收起
                NumberAnimation {
                    id: finishAnim
                    target: alertLabel
                    property: "x"
                    to: -alertLabel.width
                    easing.type: Easing.Linear
                    running: false
                    onFinished: alertPill.startCollapse()
                }
            }

            // 播报时长（秒），设置页可调，默认 5 秒
            Timer {
                id: dismissTimer
                onTriggered: alertPill.startFinishing()
            }

            // 收起动画结束后隐藏
            Timer {
                id: collapseTimer
                interval: 500
                onTriggered: alertPill.finishCollapse()
            }

            // 宽度/文字变化后等动画稳定再重算滚动状态
            Timer {
                id: settleTimer
                interval: 60
                onTriggered: alertPill.restartTicker()
            }

            onPillActiveChanged: {
                if (pillActive) {
                    hidden = false
                    finishing = false
                    collapsing = false
                    startBroadcast()
                } else {
                    dismissTimer.stop()
                    collapseTimer.stop()
                    finishing = false
                    collapsing = false
                    hidden = true
                }
                settleTimer.start()
            }

            onWidthChanged: if (pillActive && !hidden && !collapsing) settleTimer.restart()

            Component.onCompleted: {
                if (pillActive) startBroadcast()
            }

            Connections {
                target: alertLabel
                function onImplicitWidthChanged() {
                    // 子对象作用域看不到胶囊的自定义属性，必须用 id 前缀
                    if (alertPill.pillActive && !alertPill.hidden && !alertPill.finishing && !alertPill.collapsing) {
                        // 预警内容更新：重新播报并重置倒计时
                        alertPill.hidden = false
                        alertPill.startBroadcast()
                        settleTimer.restart()
                    }
                }
            }

            // 开始播报：按当前设置重新计算播报时长并启动倒计时
            function startBroadcast() {
                var secs = 5
                if (root.settings && root.settings.alert_show_time !== undefined)
                    secs = root.settings.alert_show_time
                dismissTimer.interval = Math.max(500, secs * 1000)
                dismissTimer.start()
            }

            // 到时：等当前这一轮播报结束（静止显示则直接收起）
            function startFinishing() {
                if (finishing || collapsing || hidden) return
                finishing = true
                if (!tickerAnim.running) { startCollapse(); return }
                tickerAnim.stop()
                var remain = alertLabel.x + alertLabel.width
                if (remain <= 1) { startCollapse(); return }
                finishAnim.from = alertLabel.x
                finishAnim.duration = Math.max(100, remain / 50 * 1000)
                finishAnim.start()
            }

            // 从右往左弹回城市（宽度收起动画保持可见），结束后隐藏
            function startCollapse() {
                if (collapsing || hidden) return
                finishing = false
                collapsing = true
                tickerAnim.stop()
                finishAnim.stop()
                collapseTimer.restart()
            }

            function finishCollapse() {
                if (pillActive) {
                    hidden = true
                    collapsing = false
                    finishing = false
                }
            }

            function restartTicker() {
                if (finishing || collapsing) return
                tickerAnim.stop()
                if (!pillActive || hidden || alertLabel.width <= tickerZone.width - 1) {
                    alertLabel.x = Math.max(0, (tickerZone.width - alertLabel.width) / 2)
                    return
                }
                alertLabel.x = tickerZone.width
                tickerAnim.restart()
            }
        }
    ]

    // 加载 / 缺城市 / 错误状态提示
    Quick.Text {
        id: statusText
        anchors.centerIn: parent
        width: parent.width - 24
        visible: backend.weatherStatus !== "ok"
        text: backend.weatherStatus === "need_city" ? qsTr("在插件设置中选择城市") :
              backend.weatherStatus === "error" ? qsTr("获取天气失败，将自动重试") :
              qsTr("加载中，请稍后...")
        horizontalAlignment: Quick.Text.AlignHCenter
        wrapMode: Quick.Text.Wrap
        color: Theme.currentTheme.colors.textSecondaryColor
        font.pixelSize: 13
    }

    // 天气内容
    ColumnLayout {
        anchors.fill: parent
        visible: backend.weatherStatus === "ok"
        spacing: 2

        // 主行：温度 + 天气 + 风力
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Quick.Text {
                text: backend.tempText + "°"
                font.pixelSize: 20
                font.weight: Font.DemiBold
                color: Theme.currentTheme.colors.textColor
            }
            Quick.Text {
                text: backend.weatherText
                font.pixelSize: 13
                color: Theme.currentTheme.colors.textColor
            }
            Quick.Text {
                text: backend.windText
                font.pixelSize: 10
                color: Theme.currentTheme.colors.textSecondaryColor
            }
            Item { Layout.fillWidth: true }
        }

        // 副行：最高/最低/体感/湿度（mini 模式隐藏）
        RowLayout {
            Layout.fillWidth: true
            visible: !root.miniMode
            spacing: 8
            Quick.Text {
                text: backend.hiLoText
                font.pixelSize: 10
                color: Theme.currentTheme.colors.textSecondaryColor
            }
            Quick.Text {
                text: backend.feelText !== "" ? "体感 " + backend.feelText + "°" : ""
                font.pixelSize: 10
                color: Theme.currentTheme.colors.textSecondaryColor
            }
            Quick.Text {
                text: "湿度 " + backend.humidityText + "%"
                font.pixelSize: 10
                color: Theme.currentTheme.colors.textSecondaryColor
            }
            Item { Layout.fillWidth: true }
        }
    }

    // 自动刷新定时器
    Timer {
        id: refreshTimer
        interval: Math.max(5, settings.refresh_interval) * 60 * 1000
        running: true
        repeat: true
        onTriggered: backend.refresh(currentCity)
    }

    Component.onCompleted: backend.refresh(currentCity)
}
