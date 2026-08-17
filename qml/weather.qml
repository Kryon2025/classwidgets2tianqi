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

    // 气象预警徽标（标题栏右侧）
    subtitle: [
        Rectangle {
            visible: root.alertActive
            height: 18
            radius: height / 2
            color: root.levelColor
            implicitWidth: Math.min(marquee.implicitWidth + 12, 150)
            clip: true
            MarqueeTitle {
                id: marquee
                anchors.fill: parent
                anchors.leftMargin: 6
                anchors.rightMargin: 6
                maximumWidth: parent.width
                speed: 40
                running: true
                text: "⚠ " + backend.alertTitle
                color: "#ffffff"
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
