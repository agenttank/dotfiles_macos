#!/bin/bash

if [ $1 == "on" ]; then
  sed -i 's/^outer.bottom.*/outer.bottom = 10/' ~/.config/aerospace/aerospace.toml
elif [ $1 == "off" ]; then
  sed -i 's/^outer.bottom.*/outer.bottom = 300/' ~/.config/aerospace/aerospace.toml
fi

