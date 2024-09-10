local constants = require("constants")
local settings = require("config.settings")

local maxItems <const> = 15
local menuItems = {}
local isShowingMenu = false

local frontAppWatcher = sbar.add("item", {
  drawing = false,
  updates = true,
})

local swapWatcher = sbar.add("item", {
  drawing = false,
  updates = true,
})

local function createPlaceholders()
  for index = 1, maxItems, 1 do
    local menu = sbar.add("item", constants.items.MENU .. "." .. index, {
      drawing = false,
      icon = { drawing = false },
      width = "dynamic",
      label = {
        font = {
          style = index == 1 and settings.fonts.styles.bold or settings.fonts.styles.regular,
        },
      },
      click_script = "$CONFIG_DIR/bridge/menus/bin/menus -s " .. index,
    })
    menuItems[index] = menu
  end

  sbar.add("bracket", { "/" .. constants.items.MENU .. "\\..*/" }, {
    background = {
      color = settings.colors.bg1,
      padding_left = settings.dimens.padding.item,
      padding_right = settings.dimens.padding.item,
    },
  })
end

local function updateMenus()
  sbar.set("/" .. constants.items.MENU .. "\\..*/", { drawing = false })

  sbar.exec("$CONFIG_DIR/bridge/menus/bin/menus -l", function(menus)
    local index = 1
    for menu in string.gmatch(menus, '[^\r\n]+') do
      if index < maxItems then
        menuItems[index]:set(
          {
            width = "dynamic",
            label = menu,
            drawing = isShowingMenu
          }
        )
      else
        break
      end
      index = index + 1
    end
  end)

  sbar.set(constants.items.MENU .. ".padding", { drawing = isShowingMenu })
end

frontAppWatcher:subscribe(constants.events.FRONT_APP_SWITCHED, updateMenus)

swapWatcher:subscribe(constants.events.SWAP_MENU_AND_SPACES, function(env)
  isShowingMenu = env.isShowingMenu == "on"
  updateMenus()
end)

createPlaceholders()
