local constants = require("constants")
local settings = require("config.settings")

local popupWidth <const> = settings.dimens.graphics.popup.width + 20

sbar.exec(
  "killall network_load >/dev/null; $CONFIG_DIR/bridge/network_load/bin/network_load en0 network_update 2.0"
)

local wifiUp = sbar.add("item", constants.items.WIFI .. ".up", {
  position = "right",
  width = 0,
  icon = {
    padding_left = 0,
    padding_right = 0,
    font = {
      style = settings.fonts.styles.bold,
      size = 10.0,
    },
    string = settings.icons.text.wifi.upload,
  },
  label = {
    font = {
      family = settings.fonts.numbers,
      style = settings.fonts.styles.bold,
      size = 10.0,
    },
    color = settings.colors.orange,
    string = "??? Bps",
  },
  y_offset = 4,
})

local wifiDown = sbar.add("item", constants.items.WIFI .. ".down", {
  position = "right",
  icon = {
    padding_left = 0,
    padding_right = 0,
    font = {
      style = settings.fonts.styles.bold,
      size = 10.0,
    },
    string = settings.icons.text.wifi.download,
  },
  label = {
    font = {
      family = settings.fonts.numbers,
      style = settings.fonts.styles.bold,
      size = 10,
    },
    color = settings.colors.blue,
    string = "??? Bps",
  },
  y_offset = -4,
})

local wifi = sbar.add("item", constants.items.WIFI .. ".padding", {
  position = "right",
  label = { drawing = false },
  padding_right = 0,
})

local wifiBracket = sbar.add("bracket", constants.items.WIFI .. ".bracket", {
  wifi.name,
  wifiUp.name,
  wifiDown.name
}, {
  popup = { align = "center" }
})

local ssid = sbar.add("item", {
  align = "center",
  position = "popup." .. wifiBracket.name,
  width = popupWidth,
  height = 16,
  icon = {
    string = settings.icons.text.wifi.router,
    font = {
      style = settings.fonts.styles.bold
    },
  },
  label = {
    font = {
      style = settings.fonts.styles.bold,
      size = settings.dimens.text.label,
    },
    max_chars = 18,
    string = "????????????",
  },
})

local hostname = sbar.add("item", {
  position = "popup." .. wifiBracket.name,
  background = {
    height = 16,
  },
  icon = {
    align = "left",
    string = "Hostname:",
    width = popupWidth / 2,
    font = {
      size = settings.dimens.text.label
    },
  },
  label = {
    max_chars = 20,
    string = "????????????",
    width = popupWidth / 2,
    align = "right",
  }
})

local ip = sbar.add("item", {
  position = "popup." .. wifiBracket.name,
  background = {
    height = 16,
  },
  icon = {
    align = "left",
    string = "IP:",
    width = popupWidth / 2,
    font = {
      size = settings.dimens.text.label
    },
  },
  label = {
    align = "right",
    string = "???.???.???.???",
    width = popupWidth / 2,
  }
})

local router = sbar.add("item", {
  position = "popup." .. wifiBracket.name,
  background = {
    height = 16,
  },
  icon = {
    align = "left",
    string = "Router:",
    width = popupWidth / 2,
    font = {
      size = settings.dimens.text.label
    },
  },
  label = {
    align = "right",
    string = "???.???.???.???",
    width = popupWidth / 2,
  },
})

sbar.add("item", { position = "right", width = settings.dimens.padding.item })

wifiUp:subscribe("network_update", function(env)
  local upColor = (env.upload == "000 Bps") and settings.colors.grey or settings.colors.orange
  local downColor = (env.download == "000 Bps") and settings.colors.grey or settings.colors.blue

  wifiUp:set({
    icon = { color = upColor },
    label = {
      string = env.upload,
      color = upColor
    }
  })
  wifiDown:set({
    icon = { color = downColor },
    label = {
      string = env.download,
      color = downColor
    }
  })
end)

wifi:subscribe({ "wifi_change", "system_woke", "forced" }, function(env)
  wifi:set({
    icon = {
      string = settings.icons.text.wifi.disconnected,
      color = settings.colors.magenta,
    }
  })

  sbar.exec([[ipconfig getifaddr en0]], function(ip)
    local ipConnected = not (ip == "")

    local wifiIcon
    local wifiColor

    if ipConnected then
      wifiIcon = settings.icons.text.wifi.connected
      wifiColor = settings.colors.white
    end

    wifi:set({
      icon = {
        string = wifiIcon,
        color = wifiColor,
      }
    })

    sbar.exec([[sleep 2; scutil --nwi | grep -m1 'utun' | awk '{ print $1 }']], function(vpn)
      local isVPNConnected = not (vpn == "")

      if isVPNConnected then
        wifiIcon = settings.icons.text.wifi.vpn
        wifiColor = settings.colors.green
      end

      wifi:set({
        icon = {
          string = wifiIcon,
          color = wifiColor,
        }
      })
    end)
  end)
end)

local function hideDetails()
  wifiBracket:set({ popup = { drawing = false } })
end

local function toggleDetails()
  local shouldDrawDetails = wifiBracket:query().popup.drawing == "off"

  if shouldDrawDetails then
    wifiBracket:set({ popup = { drawing = true } })
    sbar.exec("networksetup -getcomputername", function(result)
      hostname:set({ label = result })
    end)
    sbar.exec("ipconfig getifaddr en0", function(result)
      ip:set({ label = result })
    end)
    sbar.exec("ipconfig getsummary en0 | awk -F ' SSID : '  '/ SSID : / {print $2}'", function(result)
      ssid:set({ label = result })
    end)
    sbar.exec("networksetup -getinfo Wi-Fi | awk -F 'Router: ' '/^Router: / {print $2}'", function(result)
      router:set({ label = result })
    end)
  else
    hideDetails()
  end
end

local function copyLabelToClipboard(env)
  local label = sbar.query(env.NAME).label.value
  sbar.exec("echo \"" .. label .. "\" | pbcopy")
  sbar.set(env.NAME, { label = { string = settings.icons.text.clipboard, align = "center" } })
  sbar.delay(1, function()
    sbar.set(env.NAME, { label = { string = label, align = "right" } })
  end)
end

wifiUp:subscribe("mouse.clicked", toggleDetails)
wifiDown:subscribe("mouse.clicked", toggleDetails)
wifi:subscribe("mouse.clicked", toggleDetails)

ssid:subscribe("mouse.clicked", copyLabelToClipboard)
hostname:subscribe("mouse.clicked", copyLabelToClipboard)
ip:subscribe("mouse.clicked", copyLabelToClipboard)
router:subscribe("mouse.clicked", copyLabelToClipboard)
