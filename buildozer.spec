[app]
title = TikTok Bot Mobile
package.name = tiktokbot
package.domain = org.ejemplo
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,mp3
version = 1.0

requirements = python3,kivy,pygame,edge-tts,yt-dlp,psutil,aiohttp,requests

orientation = portrait
fullscreen = 0

android.permissions = INTERNET, RECORD_AUDIO, WAKE_LOCK, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE
android.api = 33
android.minapi = 21

[buildozer]
log_level = 2
warn_on_root = 1
