local settings = require("config.settings")

sbar.default({
  updates = "when_shown",
  icon = {
    font = {
      family = settings.fonts.text,
      style = settings.fonts.styles.regular,
      size = settings.dimens.text.icon,
    },
    color = settings.colors.white,
    padding_left = settings.dimens.padding.icon,
    padding_right = settings.dimens.padding.icon,
  },
  label = {
    font = {
      family = settings.fonts.text,
      style = settings.fonts.styles.regular,
      size = settings.dimens.text.label,
    },
    color = settings.colors.white,
    padding_left = settings.dimens.padding.label,
    padding_right = settings.dimens.padding.label,
  },
  background = {
    height = settings.dimens.graphics.background.height,
    corner_radius = settings.dimens.graphics.background.corner_radius,
    border_width = 0,
    image = {
      corner_radius = settings.dimens.graphics.background.corner_radius
    }
  },
  popup = {
    y_offset = settings.dimens.padding.popup,
    align = "center",
    background = {
      border_width = 0,
      corner_radius = settings.dimens.graphics.background.corner_radius,
      color = settings.colors.popup.bg,
      shadow = { drawing = true },
      padding_left = settings.dimens.padding.icon,
      padding_right = settings.dimens.padding.icon,
    },
    blur_radius = settings.dimens.graphics.blur_radius,
  },
  slider = {
    highlight_color = settings.colors.orange,
    background = {
      height = settings.dimens.graphics.slider.height,
      corner_radius = settings.dimens.graphics.background.corner_radius,
      color = settings.colors.slider.bg,
      border_color = settings.colors.slider.border,
      border_width = 1,
    },
    knob = {
      font = {
        family = settings.fonts.text,
        style = settings.fonts.styles.regular,
        size = 32,
      },
      string = settings.icons.text.slider.knob,
      drawing = false,
    },
  },
  scroll_texts = true,
})
