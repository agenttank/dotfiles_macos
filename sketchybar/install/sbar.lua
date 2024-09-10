local sbarpath = "/Users/" .. os.getenv("USER") .. "/.local/share/sketchybar_lua/"

local function exists(file)
  local ok, err, code = os.rename(file, file)
  if not ok then
    if code == 13 then
      return true
    end
  end
  return ok, err
end

local function isdir(path)
  return exists(path .. "/")
end

if not isdir(sbarpath) then
  os.execute(
    "git clone https://github.com/FelixKratz/SbarLua.git /tmp/SbarLua && cd /tmp/SbarLua && make install && rm -rf /tmp/SbarLua/"
  )
end

package.cpath = package.cpath .. ";" .. sbarpath .. "?.so"

os.execute("(cd bridge && make)")
