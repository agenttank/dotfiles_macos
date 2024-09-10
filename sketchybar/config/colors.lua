local colors <const> = {
  black = 0xff181819,
  white = 0xfff8f8f2,
  red = 0xf1cc3e44,
  green = 0xff8aff81,
  blue = 0xff5199ba,
  yellow = 0xffffff81,
  orange = 0xfff4c07b,
  magenta = 0xd3fc7ebd,
  purple = 0xff796fa9,
  other_purple = 0xff302c45,
  cyan = 0xff7bf2de,
  grey = 0xff7f8490,
  dirty_white = 0xc8cad3f5,
  dark_grey = 0xff2b2736,
  transparent = 0x00000000,
  bar = {
    bg = 0xf1151320,
    border = 0xff2c2e34,
  },
  popup = {
    bg = 0xf1151320,
    border = 0xff2c2e34,
  },
  slider = {
    bg = 0xf1151320,
    border = 0xff2c2e34,
  },
  bg1 = 0xd322212c,
  bg2 = 0xff302c45,

  with_alpha = function(color, alpha)
    if alpha > 1.0 or alpha < 0.0 then return color end
    return (color & 0x00ffffff) | (math.floor(alpha * 255.0) << 24)
  end,
}

return colors
