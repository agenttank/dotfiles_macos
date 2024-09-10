# my macOS dotfiles

## Screenshot
<p align="center">
  <img src="rice.png" />
</p>

## really great applications that I use

- Aerospace  
The best tiling window manager for MacOS
https://github.com/nikitabobko/AeroSpace

- Sketchybar  
The highly configurable top bar
https://github.com/FelixKratz/SketchyBar

- Sketchybar configuration  
a really good lua scripted Sketchybar configuration
https://github.com/bfpimentel/nixos.git

- Required Font for Sketchybar  
`font-space-mono-nerd-font`

- alacritty   
A fast terminal that lets you disable decorations 
https://github.com/alacritty/alacritty

- borders  
see what window is in focus at the moment - it makes a colored border appear
https://github.com/FelixKratz/JankyBorders

- brew packages  
see `brew.txt`

- Wallpaper  
https://www.reddit.com/r/wallpapers/  
https://www.reddit.com/r/wallpapers/comments/1eibln5/abstract_circle_3840x2160/

## Other information

- Shell  
zsh  
oh-my-zsh  

- Browser  
qutebrowser - A great browser that lets you browse the internet via keyboard/vim controls
https://qutebrowser.com/  
qutebrowser theme  
https://github.com/gicrisf/qute-city-lights  

## MacOS settings

I also changed a few settings in MacOS because the defaults interfere with this config
### make Dock and the native MacOS bar auto-hide  
somewhere in the macOS settings

### disable window animations
`defaults write -g NSAutomaticWindowAnimationsEnabled -bool false`

### reduce motion (for native fullscreen functionality and maybe some more unnecessary animations)
- System Preferences > Accessibility > Display > Reduce motion

### disable lots of MacOS keyboard shortcuts in the MacOS settings
- disable command+Q in MacOS system settings
- be ready to disable a few more, as I am unsure about what other shortcuts might collide

### Move windows by dragging any part of the window (by holding ctrl+cmd)
`defaults write -g NSWindowShouldDragOnGesture -bool true`

### Displays have separate Spaces
Enable this in MacOS settings "Desktop and dock" or else Sketchybar will not start. In generall Aerospace recommends disabling this though.  
https://nikitabobko.github.io/AeroSpace/guide#a-note-on-displays-have-separate-spaces  
Sketchybar might work with the option being disabled in the future.  
https://github.com/FelixKratz/SketchyBar/issues/495  
