# Stremio Community Subtitles Addon

![Version](https://img.shields.io/badge/version-0.5.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-Active-brightgreen.svg)

<div align="center">
  <img src="https://raw.githubusercontent.com/skoruppa/stremio-community-subtitles/refs/heads/main/static/logo.png" alt="SCS Logo" width="256">
</div>

A Stremio addon that enables you to use custom subtitles on any device – something normally only possible on desktop Stremio. Simply upload your subtitle files for the video you just started watching, and they'll be instantly available across all your devices through the addon.

Every subtitle you upload helps build a community database that benefits all users. Multiple subtitle provider integrations (OpenSubtitles, SubDL, Subsource) allow manual selection of any available subtitles and linking them to specific video versions, ensuring perfectly synchronized subtitles for future viewers.

## ✨ Features

- **📱 Cross-Device Subtitle Support** – Use custom subtitles on web, mobile, TV, or desktop
- **🌍 Community Database** – Your uploads help other users watching the same files
- **🤖 Automatic Subtitle Selection** – Subtitles are selected automatically based on your video file
- **📤 Upload Without Watching** – Upload subtitles without starting playback
- **🎯 Multiple Subtitle Providers** – Connect to OpenSubtitles, SubDL, and Subsource for enhanced subtitle search
- **🔍 Manual Provider Selection** – Choose any available subtitle from connected providers for a specific video
- **🔗 Link to Video Version** – Linked subtitles stay synced for future viewers
- **🧠 Viewing History Integration**
- **🗳️ Voting System**
- **🧹 Manage Your Data**
  - uploaded subtitles
  - your provider selections
  - your votes

### ✅ New in 0.5.0 — Multiple Subtitle Providers

The addon now supports **multiple external subtitle providers**:

✅ **OpenSubtitles** – The largest subtitle database with millions of subtitles
✅ **SubDL** – Fast and reliable subtitle source with excellent coverage
✅ **Subsource** – Additional subtitle provider for enhanced search results

**Features:**
- Connect multiple providers simultaneously
- Automatic subtitle search across all connected providers
- Manual selection from any provider
- Link provider subtitles to specific video versions
- Prioritize ASS/SSA subtitles option for better formatting support

**Previous updates (0.4.5):**
- Dual format support for ASS/SSA subtitles (original + VTT conversion)
- Switch between formats in Stremio for best compatibility

---

## 🚀 Installation

1. Visit [The Addon Website](https://stremio-community-subtitles.top)
2. Create an account and confirm your email
3. Log in
4. Go to the [configuration page](https://stremio-community-subtitles.top/configure)
5. Copy your personal manifest URL
6. Open Stremio and paste it into the addon search box, or click "Install in Stremio"
7. Done!

## 🔐 Subtitle Provider Integration

Connect to external subtitle providers from [account settings](https://stremio-community-subtitles.top/account):

**Supported Providers:**
- **OpenSubtitles** – Requires API key or account
- **SubDL** – Requires API key
- **Subsource** – Requires API key

Once connected:

- Subtitles are fetched automatically from all active providers
- You can manually select subtitles from any provider for any video
- You can **link** provider subtitles to your video version for the community

## 📱 Usage

### Quick Start

1. Start watching something in Stremio
2. Visit the addon website – your current video will appear automatically
3. Upload a subtitle or select one from connected providers
4. The subtitle becomes available instantly across devices

### Upload Without Playback

- Provide a `contentId` (IMDb or Kitsu)
- Upload subtitles even if you are not watching
- Later, you can link them to a specific video hash once confirmed in sync

### Automatic Matching

- The addon selects the best subtitle for your file
- Works with uploaded subs and all connected providers

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
- You can also "link" provider subtitles to the correct video version
- Everyone benefits from what the community uploads and links

## 🤝 Support

If you want to thank me for the addon, you can [buy me a coffee](https://buymeacoffee.com/skoruppa) ☕

## 🔗 Links

🌐 Website: [https://stremio-community-subtitles.top](https://stremio-community-subtitles.top)  
💻 Source Code: [https://github.com/skoruppa/stremio-community-subtitles](https://github.com/skoruppa/stremio-community-subtitles)

The addon is self-hostable – feel free to deploy your own instance if needed!

## 📄 License

MIT License – see [LICENSE](LICENSE) for details.
