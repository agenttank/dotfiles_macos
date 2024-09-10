local dimens <const> = require("config.dimens")

return {
  text = "SpaceMono Nerd Font",
  numbers = "SpaceMono Nerd Font",
  icons = function(size)
    local font = "sketchybar-app-font:Regular"
    return size and font .. ":" .. size or font .. ":" .. dimens.text.icon
  end,
  styles = {
    regular = "Regular",
    bold = "Bold",
  }
}
