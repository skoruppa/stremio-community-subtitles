# Stremio Community Subtitles Addon

![Version](https://img.shields.io/badge/version-0.4.2-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-Active-brightgreen.svg)

<div align="center">
  <img src="https://raw.githubusercontent.com/skoruppa/stremio-community-subtitles/refs/heads/main/static/logo.png" alt="SCS Logo" width="256">
</div>

A Stremio addon that enables you to use custom subtitles on any device – something normally only possible on desktop Stremio. Simply upload your subtitle files for the video you just started watching, and they'll be instantly available across all your devices through the addon.

Every subtitle you upload helps build a community database that benefits all users. The OpenSubtitles integration allows manual selection of any available subtitles and linking them to specific video versions, ensuring perfectly synchronized subtitles for future viewers.

## ✨ Features

- **📱 Cross-Device Subtitle Support** – Use custom subtitles on web, mobile, TV, or desktop
- **🌍 Community Database** – Your uploads help other users watching the same files
- **🤖 Automatic Subtitle Selection** – Subtitles are now selected automatically based on your video file
- **📤 Upload Without Watching** – Upload subtitles without needing to start playback
- **🎯 Manual OpenSubtitles Selection** – Choose any available OpenSubtitles subtitle for specific video
- **🔗 Link to Video Version** – You can “link” subtitles (including OpenSubtitles) to your video version for other users
- **🧠 Viewing History Integration** – Manage your subtitles based on what you've watched
- **🗳️ Voting System** – Vote for good or bad subs to help others find the best ones
- **🧹 Manage Your Data (NEW!)** – You can now see and delete:
  - your uploaded subtitles
  - your manual subtitle selections
  - your votes on subtitles

## 🚀 Installation

1. Visit [The Addon Website](https://stremio-community-subtitles.top)
2. Create an account and confirm your email
3. Log in
4. Go to the [configuration page](https://stremio-community-subtitles.top/configure)
5. Copy your personal manifest URL
6. Open Stremio and paste it into the addon search box, or click "Install in Stremio"
7. Done!

## 🔐 OpenSubtitles Integration

- You **no longer need your own API key**
- Just log in with your OpenSubtitles account from the [account settings](https://stremio-community-subtitles.top/account)
- ⚠️ Some older accounts must reconnect due to OS security changes

Once connected:

- Subtitles are fetched automatically
- You can manually change OpenSubtitles for any video
- You can **link** subtitles to your video version for the community

## 📱 Usage

### Quick Start

1. Start watching something in Stremio
2. Visit the addon website – your current video will appear automatically
3. Upload a subtitle or select one from OpenSubtitles
4. The subtitle becomes available instantly across devices

### Upload Without Playback

- Provide a `contentId` (IMDb or Kitsu)
- Upload subtitles even if you are not watching
- Later, you can link them to a specific video hash once confirmed in sync

### Automatic Matching

- The addon selects the best subtitle for your file
- Works with uploaded subs and OpenSubtitles

## 🧹 Manage Your Uploaded Data (NEW!)

A new management panels allows you to view and delete:

- Subtitles you uploaded
- Subtitle selections you made
- Your subtitle votes

If a subtitle you uploaded is bad, outdated, or replaced by a better one, you can remove it with one click.

## 🎯 How It Works

- Upload subtitles via the website while watching a video
- They're matched by **video hash**
- You (and others) can instantly use them on any device
- You can also “link” OpenSubtitles to the correct video version
- Everyone benefits from what the community uploads and links

## 🤝 Support

If you want to thank me for the addon, you can [buy me a coffee](https://buycoffee.to/skoruppa) ☕

## 🔗 Links

🌐 Website: [https://stremio-community-subtitles.top](https://stremio-community-subtitles.top)  
💻 Source Code: [https://github.com/skoruppa/stremio-community-subtitles](https://github.com/skoruppa/stremio-community-subtitles)

The addon is self-hostable – feel free to deploy your own instance if needed!

## 📄 License

MIT License – see [LICENSE](LICENSE) for details.
