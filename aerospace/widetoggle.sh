#!/usr/bin/env bash

# The output is like: "        UI Looks like: 1728 x 1117 @ 60hz"
DISPLAY_DETAILS=$(system_profiler SPDisplaysDataType | grep 'UI Looks like')

SCREEN_WIDTH=$(echo "$DISPLAY_DETAILS" | awk '{print $4}')
SCREEN_HEIGHT=$(echo "$DISPLAY_DETAILS" | awk '{print $6}')

if [ -z "$SCREEN_WIDTH" ] || [ -z "$SCREEN_HEIGHT" ]; then
    echo "Error: Could not determine screen dimensions."
    exit 1
fi

NEW_WIDTH=$((SCREEN_WIDTH / 2))
NEW_HEIGHT=$SCREEN_HEIGHT
NEW_X=$((SCREEN_WIDTH / 4)) # Position at 25% from the left to center it
NEW_Y=50 # Account for top bar

osascript -e "
try
    tell application \"System Events\" to tell window 1 of (process 1 where it is frontmost)
        try
      		set position to {$NEW_X, $NEW_Y}
            set size to {$NEW_WIDTH, $NEW_HEIGHT}
        end try
    end tell
on error errMsg
    display dialog \"AppleScript Error: \" & errMsg
end try
"
