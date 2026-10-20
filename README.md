<div align="center">
  <img src="https://raw.githubusercontent.com/tandpfun/skill-icons/main/icons/FastAPI-Dark.svg" alt="FastAPI" width="40" height="40"/>
  <img src="https://raw.githubusercontent.com/tandpfun/skill-icons/main/icons/TailwindCSS-Dark.svg" alt="Tailwind" width="40" height="40"/>
  <img src="https://raw.githubusercontent.com/tandpfun/skill-icons/main/icons/Docker.svg" alt="Docker" width="40" height="40"/>

  <h1 align="center">Nimbus</h1>
  <p align="center">
    <strong>A Modern, Elegant, Self-Hosted Web Downloader</strong>
  </p>
</div>

<p align="center">
  Nimbus is a lightweight, self-hosted web application that allows you to download videos and audio from YouTube, TikTok, X (Twitter), Instagram, Reddit, and hundreds of other platforms with just a single click. Powered by `yt-dlp` and `FastAPI`, featuring a beautiful real-time UI.
</p>

---

## ✨ Features

- **Universal Quick-Input**: Just paste the URL and hit Enter. Automatically detects the link and starts downloading.
- **Configurable Video Quality**: Choose between **Best / Max (4K/HD)**, **1080p Full HD**, **720p HD**, **480p SD**, or **360p Data Saver**. Your preference is automatically remembered.
- **Real-Time Progress**: Watch your downloads progress in real-time. Displays animated progress bars, speed, ETA, and target quality powered by WebSockets.
- **Format Toggle**: Easily switch between downloading Video (MP4) with custom resolutions or Audio Only (MP3 192kbps) via a sleek toggle.
- **YouTube High-Fidelity & Anti-Bot Engine (v1.0.2)**: Intelligently merges separate high-resolution DASH video and audio streams using `ffmpeg`, preventing 360p fallback while maintaining anti-bot mobile client resilience.
- **YouTube Cookie Manager**: Built-in web-based `cookies.txt` upload to seamlessly bypass bot verification and age restrictions with full 4K/8K fidelity.
- **Mini File Manager**: View, play, download to your local machine, or delete completed files directly from the dashboard.
- **Bulk ZIP Download**: Download all stored files on the server in a single compressed `.zip` archive with one click.
- **Bulk Delete**: Delete all completed files stored on the server with a single click and safety confirmation.
- **Dark Mode & Glassmorphism**: A beautiful, modern UI built with Tailwind CSS and Alpine.js. Responsive on both desktop and mobile.
- **Secure Access**: Simple yet effective password protection out of the box, perfect for exposing via reverse proxies or IP tunnels.
- **Non-Blocking Architecture**: Queue multiple downloads simultaneously without freezing the UI.

## 🛠️ Tech Stack

- **Backend**: Python 3.12, [FastAPI](https://fastapi.tiangolo.com/), `uvicorn`, `websockets`
- **Download Engine**: [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), `ffmpeg`
- **Frontend**: HTML5, [Tailwind CSS](https://tailwindcss.com/) (CDN), [Alpine.js](https://alpinejs.dev/) (CDN)
- **Deployment**: Docker Compose & GitHub Container Registry (`ghcr.io/opeteer/nimbus`)
- **Gateway**: Rocky Gateway Platform (Tailscale Funnel & Nginx Reverse Proxy)

## 🚀 Quick Start (Docker)

The easiest way to run Nimbus is via Docker. This ensures all dependencies (including `ffmpeg`) are perfectly isolated.

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

### Installation

1. **Clone the repository** (or download the source files):
   ```bash
   git clone https://github.com/opeteer/nimbus.git
   cd nimbus
   ```

2. **Configure your password** (Optional):
   Open `docker-compose.yml` and change the `NIMBUS_PASSWORD` environment variable to secure your instance.
   ```yaml
   environment:
     - NIMBUS_PASSWORD=your_secure_password
   ```

3. **Build and Run**:
   ```bash
   docker-compose up -d --build
   ```

4. **Access the App**:
   Open your browser and navigate to `http://localhost:8000` (or your server's IP address).
   Log in with your configured password.

## 🍪 YouTube High-Fidelity & Anti-Bot Engine (v1.0.2)

YouTube frequently enforces anti-bot challenges (*"Sign in to confirm you're not a bot"*) on server and datacenter IP addresses:
- **Automatic Mobile Client Fallback**: Nimbus automatically configures `yt-dlp` to query YouTube via mobile player clients (`ios`, `android`, `mweb`), resolving the majority of bot detection blocks out of the box without manual configuration.
- **Built-in Cookie Manager**: For age-restricted or strictly guarded videos, click the **Cookies** button in the dashboard header to upload a `cookies.txt` file or paste Netscape cookie text directly from your browser (e.g., using the *Get cookies.txt LOCALLY* browser extension).
- **Zero-Downtime Persistence**: Cookies are saved to `./downloads/cookies.txt`, meaning they persist across container updates and restarts through the mounted volume. You can also manually place a `cookies.txt` into the `./downloads/` directory at any time.

## 📂 File Storage

All downloaded files are automatically saved to the `downloads` directory located in the root of the project folder. This directory is mounted as a volume in Docker, meaning your files are persisted safely on your host machine even if the container is restarted or rebuilt.

## 🔒 Security Note

Nimbus uses a simple HTTP-only cookie-based authentication. If you are exposing this to the public internet, it is **highly recommended** to place Nimbus behind a reverse proxy (like Nginx, Traefik, or Cloudflare Tunnels) and enable HTTPS/SSL.

---

<div align="center">
  <i>Built with ❤️ for modern self-hosters.</i>
</div>
