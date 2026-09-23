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
- **Real-Time Progress**: Watch your downloads progress in real-time. Displays animated progress bars, speed, and ETA powered by WebSockets.
- **Format Toggle**: Easily switch between downloading the Best Quality Video (MP4) or Audio Only (MP3/M4A) via a sleek toggle.
- **Mini File Manager**: View, play, download to your local machine, or delete completed files directly from the dashboard.
- **Dark Mode & Glassmorphism**: A beautiful, modern UI built with Tailwind CSS and Alpine.js. Responsive on both desktop and mobile.
- **Secure Access**: Simple yet effective password protection out of the box, perfect for exposing via reverse proxies or IP tunnels.
- **Non-Blocking Architecture**: Queue multiple downloads simultaneously without freezing the UI.

## 🛠️ Tech Stack

- **Backend**: Python 3.11, [FastAPI](https://fastapi.tiangolo.com/), `uvicorn`, `websockets`
- **Download Engine**: [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), `ffmpeg`
- **Frontend**: HTML5, [Tailwind CSS](https://tailwindcss.com/) (CDN), [Alpine.js](https://alpinejs.dev/) (CDN)
- **Deployment**: Docker & Docker Compose

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

## 📂 File Storage

All downloaded files are automatically saved to the `downloads` directory located in the root of the project folder. This directory is mounted as a volume in Docker, meaning your files are persisted safely on your host machine even if the container is restarted or rebuilt.

## 🔒 Security Note

Nimbus uses a simple HTTP-only cookie-based authentication. If you are exposing this to the public internet, it is **highly recommended** to place Nimbus behind a reverse proxy (like Nginx, Traefik, or Cloudflare Tunnels) and enable HTTPS/SSL.

---

<div align="center">
  <i>Built with ❤️ for modern self-hosters.</i>
</div>
