import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

SettingsLayout {
    id: root

    // 2 代组件设置页只注入 settings + instanceId（无 backend），
    // 全部配置读写走 settings，点"确定"后由主程序保存并同步给组件本体

    // 自动定位：从组件配置读取初始值，变更写入局部 settings
    property bool autoValue: settings.auto_location !== undefined ? settings.auto_location : true
    onAutoValueChanged: settings.auto_location = autoValue

    // 城市名，始终与显示同步
    property string cityText: settings.city !== undefined ? settings.city : ""
    onCityTextChanged: settings.city = cityText

    // 刷新间隔当前值（分钟），始终与显示同步
    property int intervalValue: settings.refresh_interval !== undefined ? settings.refresh_interval : 30
    onIntervalValueChanged: settings.refresh_interval = intervalValue

    // 预警播报时长当前值（秒），始终与显示同步
    property int alertTimeValue: settings.alert_show_time !== undefined ? settings.alert_show_time : 5
    onAlertTimeValueChanged: settings.alert_show_time = alertTimeValue

    SettingCard {
        Layout.fillWidth: true
        title: "自动定位"
        description: "开启后自动获取当前位置天气（IP 定位，无需手动填城市）；关闭时使用下方城市。"

        Switch {
            checked: root.autoValue
            onCheckedChanged: root.autoValue = checked
        }
    }

    SettingCard {
        Layout.fillWidth: true
        title: "城市"
        description: root.autoValue ? "已开启自动定位，此设置仅在关闭自动定位时生效。" :
                                     "输入城市名（如：北京、成都、上海），回车或失焦后生效。"

        TextField {
            Layout.fillWidth: true
            placeholderText: "例如：北京"
            text: root.cityText
            enabled: !root.autoValue
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

    SettingCard {
        Layout.fillWidth: true
        title: "预警播报时长"
        description: "预警弹出并滚动播报几秒后自动收起（秒），点击加减按钮以 1 调整。"

        RowLayout {
            spacing: 8
            Button {
                text: "−"
                implicitWidth: 36
                onClicked: alertTimeValue = Math.max(1, alertTimeValue - 1)
            }
            Text {
                Layout.preferredWidth: 80
                horizontalAlignment: Text.AlignHCenter
                text: alertTimeValue + " 秒"
            }
            Button {
                text: "+"
                implicitWidth: 36
                onClicked: alertTimeValue = Math.min(60, alertTimeValue + 1)
            }
        }
    }
}
