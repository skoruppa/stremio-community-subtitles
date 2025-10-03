# Stremio Community Subtitles Addon

![Version](https://img.shields.io/badge/version-0.3.2-blue.svg)
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

## 🚀 Installation

To install the addon:

1. Visit [The Addon Website](https://stremio-community-subtitles.top)
2. Create an account and confirm your email
3. Log in
4. Go to the [configuration page](https://stremio-community-subtitles.top/configure)
5. Copy your personal manifest URL
6. Open Stremio and paste it into the addon search box, or click "Install in Stremio"
7. Done!

## 🔐 OpenSubtitles Integration (Updated!)

OpenSubtitles integration has changed (v0.3):

- You **no longer need your own API key**
- Just log in with your OpenSubtitles account from the [account settings](https://stremio-community-subtitles.top/account)
- ⚠️ **IMPORTANT:** Existing users must reconnect their account due to changes requested by OpenSubtitles team

Once connected, you can:

- Subs will be served automatically 
- Change available OpenSubtitles for any video
- Select and **link** subtitles to your version if you want help other users

## 📱 Usage

### Quick Start:

1. **Start Watching** something in Stremio
2. **Visit the Addon Website** – your current video will show on the homepage
3. **Upload a subtitle** (or choose from OpenSubtitles)
4. **Subtitle is available instantly** across your devices

### New: Upload Without Playback

You can now upload subtitles **without starting a video**:

- Provide a `contentId` (IMDb or Kitsu supported)
- Subtitles are added to the database, but won't have a hash assigned
- You can **link** them later to a video after confirming they are synced
- A personal “uploaded subtitles” page is coming soon

### New: Automatic Subtitle Matching

- The addon now chooses the best subtitle automatically
- Works with both your uploads and OpenSubtitles
- Manual selection is still possible, but often unnecessary

## 🎯 How It Works

This addon solves a key problem: **Stremio mobile and TV apps don’t support external subtitles**.

**How we fix it:**

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
