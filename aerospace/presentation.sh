#!/bin/bash

if [ $1 == "on" ]; then
  sed -i '' 's/^outer.bottom.*/outer.bottom = 300/' ~/.config/aerospace/aerospace.toml
  sed -i '' "s/\(outer\.top = *\[.*\), 52]/\1, 300]/" ~/.config/aerospace/aerospace.toml
  aerospace reload-config
elif [ $1 == "off" ]; then
  sed -i '' 's/^outer.bottom.*/outer.bottom = 10/' ~/.config/aerospace/aerospace.toml
  sed -i '' "s/\(outer\.top = *\[.*\), 300]/\1, 52]/" ~/.config/aerospace/aerospace.toml
  aerospace reload-config
fi

