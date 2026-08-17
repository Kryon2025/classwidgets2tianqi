import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

SettingsLayout {
    id: root

    // 城市名，始终与显示同步
    property string cityText: ""
    onCityTextChanged: settings.city = cityText

    // 刷新间隔当前值（分钟），始终与显示同步
    property int intervalValue: 30
    onIntervalValueChanged: settings.refresh_interval = intervalValue

    // 一次性读取持久化设置（旧实例可能缺少新键，缺省回退默认值）
    Component.onCompleted: {
        intervalValue = settings.refresh_interval !== undefined ? settings.refresh_interval : 30
        cityText = settings.city !== undefined ? settings.city : ""
    }

    SettingCard {
        Layout.fillWidth: true
        title: "城市"
        description: "输入城市名（如：北京、成都、上海），回车或失焦后生效。"

        TextField {
            Layout.fillWidth: true
            placeholderText: "例如：北京"
            text: root.cityText
            onEditingFinished: root.cityText = text
        }
    }

    SettingCard {
        Layout.fillWidth: true
        title: "刷新间隔"
        description: "每隔多久自动刷新一次天气（分钟），点击加减按钮以 5 调整。"

        RowLayout {
            spacing: 8
            Button {
                text: "−"
                implicitWidth: 36
                onClicked: intervalValue = Math.max(5, intervalValue - 5)
            }
            Text {
                Layout.preferredWidth: 80
                horizontalAlignment: Text.AlignHCenter
                text: intervalValue + " 分钟"
            }
            Button {
                text: "+"
                implicitWidth: 36
                onClicked: intervalValue = Math.min(120, intervalValue + 5)
            }
        }
    }

    SettingCard {
        Layout.fillWidth: true
        title: "显示预警"
        description: "有气象局预警时，在组件标题栏显示彩色预警徽标。"

        Switch {
            checked: settings.show_alerts
            onCheckedChanged: settings.show_alerts = checked
        }
    }
}
