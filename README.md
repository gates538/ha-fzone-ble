# FZONE BLE Aquarium Light for Home Assistant

[![HACS Validation](https://github.com/gates538/ha-fzone-ble/actions/workflows/validate.yaml/badge.svg)](https://github.com/gates538/ha-fzone-ble/actions/workflows/validate.yaml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A custom Home Assistant integration to control **FZONE BLE Aquarium LED Lights** (SmartAqua BRITE, F102 Series, and compatible BLE lamps) with full **RGBW** and brightness control.

100% Local Control — No Cloud Required.

---

## 🐠 Features

- 💡 **Native Light Entity**: Full integration into Home Assistant's `light` domain.
- 🎨 **RGBW Color Picker & Brightness Slider**: Complete 4-channel control (Red, Green, Blue, Cold/Warm White).
- 📶 **ESPHome Bluetooth Proxy Support**: Control the lamp seamlessly from anywhere in your home using an inexpensive ESP32 Bluetooth Proxy (e.g., M5Stack Atom Lite).
- 🔄 **Auto Discovery**: Automatically detects nearby FZONE lamps and prompts for setup in the UI.
- ⚡ **Ultra Low Latency**: Fast, reliable command execution using `bleak-retry-connector`.

---

## 📦 Supported Hardware

- **FZONE SmartAqua BRITE (F102 Series)**
- FZONE LED lamps utilizing the `0x55 0xAA 0x06` BLE protocol (Service UUID `0000ae30-...` / Write Char `0000ae01-...`)
- Compatible Chihiros / SmartAqua BLE fixtures

---

## 🚀 Installation

### Option 1: HACS (Recommended)

1. Open **HACS** in your Home Assistant dashboard.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Enter repository URL: `https://github.com/gates538/ha-fzone-ble`
4. Set category to **Integration** and click **Add**.
5. Find **FZONE BLE Aquarium Light** in the store and click **Download**.
6. Restart Home Assistant.

### Option 2: Manual Installation

1. Download the latest release from the [Releases](https://github.com/gates538/ha-fzone-ble/releases) tab.
2. Copy the `custom_components/fzone_ble` folder into your Home Assistant `<config>/custom_components/` directory.
3. Restart Home Assistant.

---

## ⚙️ Configuration

1. In Home Assistant, go to **Settings** ➡️ **Devices & Services**.
2. Click **+ Add Integration** and search for **FZONE BLE Aquarium Light**.
3. Select your discovered lamp from the list (or manually enter its Bluetooth MAC address, e.g., `F1:02:01:EB:A3:65`).
4. Click **Submit**. Your aquarium light is now ready to use!

---

## 📡 Using with ESPHome Bluetooth Proxy (Recommended)

If your Home Assistant server is far from your aquarium, you can use any ESP32 board (such as the **M5Stack Atom Lite**) as a Bluetooth Proxy.

Example ESPHome configuration:

```yaml
esphome:
  name: fzone-bt-proxy
  friendly_name: FZONE Bluetooth Proxy

esp32:
  board: m5stack-atom
  framework:
    type: esp-idf

logger:
  level: INFO

api:

ota:
  - platform: esphome

wifi:
  ssid: "YOUR_WIFI_SSID"
  password: "YOUR_WIFI_PASSWORD"
  power_save_mode: none
  fast_connect: true

esp32_ble_tracker:
  scan_parameters:
    interval: 1100ms
    window: 1100ms
    active: true

bluetooth_proxy:
  active: true
```

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
