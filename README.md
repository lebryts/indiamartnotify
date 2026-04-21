# IndiaMart Lead Notifier (Cocopeat)

A professional monitoring tool for IndiaMart buy leads. It filters leads based on your specific requirements and sends instant notifications to your mobile phone.

## Features
- **High-Value Filtering**: Only notifies you for orders > 3-4 Lakhs or > 10 Tons.
- **Mobile Notifications**: Uses the `ntfy` app for instant push notifications.
- **Modern UI**: A premium, mobile-responsive dashboard to toggle monitoring.
- **Background Polling**: Checks for new leads every 5 minutes.

## 🚀 Deployment Guide (Vercel + Cron-job.org)

This setup allows **24/7 monitoring every 2 minutes for free** without needing your laptop.

### 1. Push to GitHub
1.  Initialize git: `git init`
2.  Add files: `git add .`
3.  Commit: `git commit -m "Vercel monitoring setup"`
4.  Push to a new GitHub repository.

### 2. Deploy to Vercel
1.  Import the repository into **Vercel**.
2.  **Storage Tab**: Create a **KV (Redis)** database and click "Connect".
3.  **Environment Variables**: Add a variable called `CRON_SECRET` and set it to any random password (e.g., `Cocopeat2026`).

### 3. Setup 2-Minute Cron (Cron-job.org)
1.  Sign up for a free account at **[Cron-job.org](https://cron-job.org/)**.
2.  Create a new Cron Job:
    *   **URL**: `https://your-project.vercel.app/api/cron?key=YOUR_CRON_SECRET`
    *   **Schedule**: Every 2 minutes.
3.  Click "Save".

### 4. Enable Notifications
1.  Open your Vercel URL on your phone.
2.  Turn the toggle **ON**.
3.  Subscribe to the `ntfy` topic shown on the screen.

---
*Note: Your laptop can now sleep. The cloud will handle everything!*
