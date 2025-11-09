# Stremio Community Subtitles Addon

![Version](https://img.shields.io/badge/version-0.4.5-blue.svg)
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
- **🤖 Automatic Subtitle Selection** – Subtitles are selected automatically based on your video file
- **📤 Upload Without Watching** – Upload subtitles without starting playback
- **🎯 Manual OpenSubtitles Selection** – Choose any available OpenSubtitles subtitle for a specific video
- **🔗 Link to Video Version** – Linked subtitles stay synced for future viewers
- **🧠 Viewing History Integration**
- **🗳️ Voting System**
- **🧹 Manage Your Data**
  - uploaded subtitles
  - your OpenSubtitles selections
  - your votes

### ✅ New in 0.4.5 — Better ASS/SSA Support

Until now, `.ass` / `.ssa` subtitles were always **converted** to `.vtt`.  
This caused issues:

- Stremio has inconsistent support for ASS depending on platform and playback engine
- Converting to VTT caused loss of formatting
- Some of the same rendering bugs happen in VTT  
  ref: https://github.com/Stremio/stremio-bugs/issues/1404

So starting from **0.4.5**:

✅ The addon stores **both** versions:
- original `.ass` / `.ssa`
- converted `.vtt`

✅ In Stremio, the user can **switch** between them  
This allows choosing whichever works best on a given device.
This way you can pick the "least broken" option for your platform.

---

## 🚀 Installation

1. Visit [The Addon Website](https://stremio-community-subtitles.top)
2. Create an account and confirm your email
3. Log in
4. Go to the [configuration page](https://stremio-community-subtitles.top/configure)
5. Copy your personal manifest URL
6. Open Stremio and paste it into the addon search box, or click "Install in Stremio"
7. Done!

## 🔐 OpenSubtitles Integration

- Log in from the [account settings](https://stremio-community-subtitles.top/account)

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

## 🧹 Manage Your Uploaded Data

Management panels allows you to view and delete:
- your uploaded subtitles
- your manual subtitle selections
- your votes

## 🔐 Privacy

Read the privacy policy here:  
➡️ **[PRIVACY.md](https://github.com/skoruppa/stremio-community-subtitles/blob/main/privacy.md)**

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
