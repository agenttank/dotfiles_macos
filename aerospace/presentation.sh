#!/bin/bash

# This script is used to change the top and bottom padding of the outer container in the Aerospace theme.

presentation_pixel_gaps=300
top_normal_pixel_gaps=52
bottom_normal_pixel_gaps=10

if [ $1 == "on" ]; then
  sed -i '' "s/\(outer\.top = *\[.*\), $top_normal_pixel_gaps]/\1, $presentation_pixel_gaps]/" ~/.config/aerospace/aerospace.toml
  sed -i '' "s/\(outer\.bottom = *\[.*\), $bottom_normal_pixel_gaps]/\1, $presentation_pixel_gaps]/" ~/.config/aerospace/aerospace.toml
  osascript -e 'tell application "System Events" to set picture of every desktop to "/Users/stefan.pinter/Pictures/Wallpapers/Brp_wallpaper_blue.png"'
  aerospace reload-config
elif [ $1 == "off" ]; then
  sed -i '' "s/\(outer\.top = *\[.*\), $presentation_pixel_gaps]/\1, $top_normal_pixel_gaps]/" ~/.config/aerospace/aerospace.toml
  sed -i '' "s/\(outer\.bottom = *\[.*\), $presentation_pixel_gaps]/\1, $bottom_normal_pixel_gaps]/" ~/.config/aerospace/aerospace.toml
  osascript -e 'tell application "System Events" to set picture of every desktop to "/Users/stefan.pinter/.config/bluering.png"'
  aerospace reload-config
fi

